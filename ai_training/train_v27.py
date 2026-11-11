"""
S-CLIPS v2.7 — pelatihan model subjek SINTA + kalibrasi + perakitan bundle.

Pemakaian:
  python train_v27.py eval-title       # latih di 80% (split per judul), uji 20% lewat kode layanan
  python train_v27.py eval-publisher   # latih di 80% (split per penerbit), uji 20% penerbit baru
  python train_v27.py final            # latih di seluruh data berlabel -> sclips_models_v2.7.pkl

Semua teks fitur dibangun oleh fungsi di sclips_ml_service.py (identik saat training & serving).
"""
import sys, os, io, json, time, pickle, hashlib, collections, importlib.util
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault('SCLIPS_TASK_DB_PATH', os.path.join(HERE, 'sclips_tasks_train.db'))
spec = importlib.util.spec_from_file_location('sclips_ml_service', os.path.join(HERE, 'sclips_ml_service.py'))
svc = importlib.util.module_from_spec(spec); sys.modules['sclips_ml_service'] = svc; spec.loader.exec_module(svc)

import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline, FeatureUnion
from sklearn.preprocessing import MaxAbsScaler, Normalizer
from sklearn.svm import LinearSVC
from sklearn.calibration import CalibratedClassifierCV
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import GroupKFold, StratifiedGroupKFold, GroupShuffleSplit

DATA_XLSX = os.environ.get('SCLIPS_TRAIN_XLSX', os.path.join(HERE, 'journals_classified_v2.6.xlsx'))
V26_PKL = os.environ.get('SCLIPS_V26_PKL', os.path.join(HERE, 'sclips_models_v2.6.pkl'))
SINTA10 = svc.SINTA_10_SUBJECTS
MD_MIN = svc.MULTIDISCIPLINARY_MIN_SINTA_SUBJECTS
C_SINTA = 0.25
RUMPUN = svc.SINTA_TO_SCOPUS_MAP
RN = sorted(set(RUMPUN.values()))


def load_data():
    df = pd.read_excel(DATA_XLSX, sheet_name='2_Full_16768_Jurnal')
    df['pub'] = df.publisher_name_clean.fillna(df.publisher_name_raw).fillna('').astype(str)
    df.loc[df.pub.str.strip().isin(['-', 'nan']), 'pub'] = ''
    df['pkey'] = df.pub.map(svc.publisher_key)
    df['title'] = df.journal_title.astype(str)
    df['parts'] = df.subject_sinta_asli.map(svc.parse_sinta_subjects)
    df['tkey'] = df.title.str.lower().str.replace(r'[^a-z0-9]', '', regex=True)
    return df


def subject_weights(parts):
    if len(parts) >= MD_MIN:
        return {svc.MULTIDISCIPLINARY_LABEL: 1.0}
    return {p: 1.0 / len(parts) for p in parts}


def publisher_sums(frame):
    sums = collections.defaultdict(collections.Counter); n = collections.Counter()
    for key, parts in zip(frame.pkey, frame.parts):
        if key and parts:
            for s_, w in subject_weights(parts).items():
                sums[key][s_] += w
            n[key] += 1
    return sums, n


def prior_for(key, parts_self, sums, n, exclude_self):
    if not key or key not in n:
        return None
    cnt = collections.Counter(sums[key]); m = n[key]
    if exclude_self and parts_self:
        for s_, w in subject_weights(parts_self).items():
            cnt[s_] -= w
        m -= 1
    if m < 1:
        return None
    tot = sum(v for v in cnt.values() if v > 1e-9)
    return {s_: v / tot for s_, v in cnt.items() if v > 1e-9} if tot > 0 else None


def build_texts(frame, sums, n, exclude_self):
    texts, has_prior = [], []
    for t, p, key, parts in zip(frame.title, frame.pub, frame.pkey, frame.parts):
        pr = prior_for(key, parts, sums, n, exclude_self)
        texts.append(svc.build_subject_text_v27(t, p, pr)); has_prior.append(bool(pr))
    return texts, np.array(has_prior)


def make_pipeline(cv):
    word = TfidfVectorizer(analyzer='word', ngram_range=(1, 2), min_df=2, sublinear_tf=True)
    char = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), min_df=2, sublinear_tf=True, max_features=30000)
    return Pipeline([('tfidf', FeatureUnion([('word', word), ('char', char)])), ('scaler', MaxAbsScaler()),
                     ('norm', Normalizer(norm='l2')),
                     ('clf', CalibratedClassifierCV(LinearSVC(C=C_SINTA, max_iter=10000, random_state=42),
                                                    method='sigmoid', cv=cv, ensemble=False))])


def fit_weighted(texts, parts_list):
    """Satu baris per subjek SINTA jurnal, bobot 1/k (jurnal dengan banyak subjek tidak mendominasi)."""
    X, y, w, g = [], [], [], []
    for i, (x, parts) in enumerate(zip(texts, parts_list)):
        for s_ in parts:
            X.append(x); y.append(s_); w.append(1.0 / len(parts)); g.append(i)
    y, w, g = np.array(y), np.array(w), np.array(g)
    splits = list(GroupKFold(n_splits=5).split(X, y, groups=g))  # kalibrasi tanpa bocor antar-baris jurnal yang sama
    pipe = make_pipeline(splits)
    pipe.fit(X, y, clf__sample_weight=w)
    pipe.named_steps['clf'].cv = 5  # buang indeks split dari objek yang dipickle
    return pipe


def score_rows(P, classes):
    classes = list(classes); n = len(P)
    order = np.argsort(-P, axis=1)
    s1 = P[np.arange(n), order[:, 0]]; s2 = s1 + P[np.arange(n), order[:, 1]]
    R = np.zeros((n, len(RN)))
    for j, c in enumerate(classes):
        R[:, RN.index(RUMPUN[c])] += P[:, j]
    return order, s1, s2, R


def correctness(order, R, classes, parts):
    classes = np.array(classes); n = len(parts)
    c1 = np.array([classes[order[i, 0]] in parts[i] for i in range(n)])
    c2 = np.array([(classes[order[i, 0]] in parts[i]) or (classes[order[i, 1]] in parts[i]) for i in range(n)])
    rtop = np.array(RN)[R.argmax(1)]
    cr = np.array([rtop[i] in {RUMPUN[x] for x in parts[i]} for i in range(n)])
    return c1, c2, cr


def iso(x, y):
    return IsotonicRegression(out_of_bounds='clip', y_min=0.0, y_max=1.0).fit(x, y.astype(float))


def train_subject_model(lab, log=print):
    """OOF (5 fold, kelompok per judul) -> kalibrator per status prior penerbit; lalu model final di seluruh `lab`."""
    oof_P = None; classes = None; oof_has = np.zeros(len(lab), dtype=bool)
    for k, (a, b) in enumerate(GroupKFold(n_splits=5).split(np.arange(len(lab)), groups=lab.tkey.values)):
        A, B = lab.iloc[a], lab.iloc[b]
        sums, n = publisher_sums(A)
        XA, _ = build_texts(A, sums, n, exclude_self=True)
        XB, hasB = build_texts(B, sums, n, exclude_self=False)
        m = fit_weighted(XA, A.parts.tolist())
        cl = list(m.named_steps['clf'].classes_)
        if oof_P is None:
            classes = cl; oof_P = np.zeros((len(lab), len(cl)))
        oof_P[b] = m.predict_proba(XB)[:, [cl.index(c) for c in classes]]
        oof_has[b] = hasB
        log(f'  OOF fold {k} selesai')
    order, s1, s2, R = score_rows(oof_P, classes)
    c1, c2, cr = correctness(order, R, classes, lab.parts.tolist())
    calib = {}
    for kind, x, y in (('single', s1, c1), ('pair', s2, c2), ('rumpun', R.max(1), cr)):
        calib[kind] = {'known': iso(x[oof_has], y[oof_has]), 'new': iso(x[~oof_has], y[~oof_has])}
    oof_stats = {'n': int(len(lab)), 'with_publisher_prior_pct': round(oof_has.mean() * 100, 1),
                 'top1_inset_pct': round(c1.mean() * 100, 2)}
    sums, n = publisher_sums(lab)
    X, _ = build_texts(lab, sums, n, exclude_self=True)
    final = fit_weighted(X, lab.parts.tolist())
    serve_prior = {key: prior_for(key, [], sums, n, False) for key in n}
    serve_prior = {k: {s_: round(v, 4) for s_, v in pr.items()} for k, pr in serve_prior.items() if pr}
    return final, calib, serve_prior, oof_stats


def publisher_fallback_stats(df):
    res = [svc.resolve_publisher_type_deterministic(str(c) if pd.notna(c) else '', str(r) if pd.notna(r) else '')
           for c, r in zip(df.publisher_name_clean, df.publisher_name_raw)]
    reason = pd.Series([b for a, b in res], index=df.index)
    d = df[reason.str.contains('Entitas Penerbit Independen') & df.old_publisher_type.notna()]
    default_conf = round(float((d.old_publisher_type == 'COM').mean() * 100), 1)
    labeled = df[df.predicted_publisher_type.isin(svc.PUBLISHER_TYPES)]
    vc = labeled.predicted_publisher_type.value_counts(normalize=True)
    return {'default_independent_label': 'COM', 'default_independent_conf': default_conf,
            'default_independent_basis_n': int(len(d)),
            'no_name_label': str(vc.index[0]), 'no_name_conf': round(float(vc.iloc[0] * 100), 1),
            'no_name_basis_n': int(len(labeled))}


def load_v26_bundle():
    raw = open(V26_PKL, 'rb').read()
    return svc._safe_load_pickle_bytes(raw)


def assemble_bundle(final, calib, serve_prior, fallback, v26, extra):
    return {
        'model_version': 'v2.7-LinearSVM-Calibrated-Lexicon-16768',
        'trained_sklearn_version': sklearn.__version__,
        'publisher_type_pipeline': v26['publisher_type_pipeline'],
        'subject_scopus_27_pipeline': v26['subject_scopus_27_pipeline'],
        'subject_sinta_pipeline': {'sklearn_pipeline': final, 'training': 'multi_subject_weighted_1_over_k',
                                   'text_builder': 'build_subject_text_v27'},
        'subject_calibration': calib,
        'publisher_subject_prior': serve_prior,
        'publisher_fallback': fallback,
        'verified_publisher_overrides': v26.get('verified_publisher_overrides', {}),
        'publisher_db_counts': v26.get('publisher_db_counts', {}),
        'optimal_thresholds': {'label_confidence_pct': svc.DEFAULT_LABEL_CONFIDENCE_THRESHOLD,
                               'publisher_type_pct': svc.DEFAULT_PUBLISHER_CONFIDENCE_THRESHOLD},
        'multidisciplinary_min_sinta_subjects': MD_MIN,
        **extra,
    }


def predictor_from_bundle(bundle, tmp_path):
    raw = pickle.dumps(bundle, protocol=pickle.HIGHEST_PROTOCOL)
    open(tmp_path, 'wb').write(raw)
    sha = hashlib.sha256(raw).hexdigest()
    return svc.SClipsMLPredictor(tmp_path, expected_sha256=sha), sha, len(raw)


def items_of(frame, with_subject=False):
    out = []
    for r in frame.itertuples():
        d = {'journal_id': int(r.journal_id), 'journal_title': str(r.journal_title)}
        if pd.notna(r.publisher_name_raw): d['publisher_name_raw'] = str(r.publisher_name_raw)
        if pd.notna(r.publisher_name_clean): d['publisher_name_clean'] = str(r.publisher_name_clean)
        if pd.notna(r.publisher_id): d['publisher_id'] = int(r.publisher_id)
        if pd.notna(r.total_journals_publisher) and r.total_journals_publisher > 0:
            d['total_journals_publisher'] = int(r.total_journals_publisher)
        if with_subject and pd.notna(r.subject_sinta_asli): d['subject_sinta'] = str(r.subject_sinta_asli)
        out.append(d)
    return out


def evaluate_service(pred, te, v26_is_ood):
    """Uji lewat predict_batch layanan (TANPA subject_sinta) terhadap subjek SINTA asli jurnal uji."""
    res = []
    items = items_of(te)
    for i in range(0, len(items), 1000):
        res += pred.predict_batch(items[i:i + 1000])
    out = pd.DataFrame(res)
    parts = te.parts.tolist()
    lvl = out.subject_label_level.values; conf = out.subject_label_confidence.values
    subj = out.predicted_subject_sinta_multilabel.str.split(', ')
    top1 = out.predicted_subject_sinta.values
    ok = []
    for i in range(len(out)):
        if lvl[i] == 'rumpun':
            ok.append(out.subject_label.iloc[i] in {RUMPUN[x] for x in parts[i]})
        else:
            ok.append(any(s_ in parts[i] for s_ in subj.iloc[i]))
    ok = np.array(ok)
    top1_ok = np.array([t in p for t, p in zip(top1, parts)])
    both_ok = np.array([all(s_ in parts[i] for s_ in subj.iloc[i]) for i in range(len(out))])
    r = {'n_test': int(len(out)), 'label_correct_pct': round(ok.mean() * 100, 2),
         'top1_inset_pct': round(top1_ok.mean() * 100, 2),
         'label_conf_ge70_pct': round((conf >= 70).mean() * 100, 2),
         'mean_label_confidence_pct': round(float(conf.mean()), 2),
         'unknown_label_count': int((out.subject_label == 'Unknown').sum() + (out.predicted_publisher_type == 'Unknown').sum()),
         'levels': {}}
    for L_ in ('subjek', 'dua_subjek', 'rumpun'):
        m = lvl == L_
        if m.any():
            r['levels'][L_] = {'coverage_pct': round(m.mean() * 100, 2), 'correct_pct': round(ok[m].mean() * 100, 2),
                               'mean_conf_pct': round(float(conf[m].mean()), 2)}
            if L_ == 'dua_subjek':
                r['levels'][L_]['both_correct_pct'] = round(both_ok[m].mean() * 100, 2)
    bands = [(70, 80), (80, 90), (90, 101)]
    r['reliability'] = [{'band': f'{a}-{min(b, 100)}', 'n': int(((conf >= a) & (conf < b)).sum()),
                         'mean_conf': round(float(conf[(conf >= a) & (conf < b)].mean()), 2) if ((conf >= a) & (conf < b)).any() else None,
                         'actual_correct': round(float(ok[(conf >= a) & (conf < b)].mean() * 100), 2) if ((conf >= a) & (conf < b)).any() else None}
                        for a, b in bands]
    hp = np.array([p is not None for p in [None] * 0])  # placeholder (prior status not exposed per row)
    m = v26_is_ood
    r['v26_unknown_subset'] = {'n': int(m.sum()), 'label_correct_pct': round(ok[m].mean() * 100, 2),
                               'top1_inset_pct': round(top1_ok[m].mean() * 100, 2),
                               'single_subject_pct': round((lvl[m] == 'subjek').mean() * 100, 2)}
    per_class = {}
    for c in SINTA10:
        mm = top1 == c
        if mm.any():
            per_class[c] = {'predicted_n': int(mm.sum()), 'precision_inset_pct': round(top1_ok[mm].mean() * 100, 2)}
        have = np.array([c in p for p in parts])
        if have.any():
            per_class.setdefault(c, {})['recall_any_pct'] = round(np.mean([c == t or c in s_ for t, s_ in zip(top1[have], subj[have])]) * 100, 2)
    r['per_class'] = per_class
    return r, out


def main(mode):
    t0 = time.time()
    df = load_data()
    lab = df[df.parts.str.len() > 0].copy()
    log = lambda m: print(f'[{time.time() - t0:7.1f}s] {m}', flush=True)
    log(f'data {len(df)} jurnal, berlabel {len(lab)}')
    v26 = load_v26_bundle()
    fallback = publisher_fallback_stats(df)
    log(f'fallback penerbit: {fallback}')
    if mode.startswith('eval'):
        if mode == 'eval-title':
            y_strat = lab.parts.str[0]
            tr_idx, te_idx = next(StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42).split(lab, y_strat, groups=lab.tkey))
        else:
            g = lab.pkey.where(lab.pkey != '', lab.tkey)
            tr_idx, te_idx = next(GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42).split(lab, groups=g))
        tr, te = lab.iloc[tr_idx], lab.iloc[te_idx]
        final, calib, prior, oof = train_subject_model(tr, log)
        bundle = assemble_bundle(final, calib, prior, fallback, v26, {'evaluation_split': mode})
        pred, sha, size = predictor_from_bundle(bundle, os.path.join(HERE, f'tmp_{mode}.pkl'))
        r, out = evaluate_service(pred, te, te.is_ood.values.astype(bool))
        r.update({'split': mode, 'n_train': int(len(tr)), 'oof': oof, 'secs': round(time.time() - t0)})
        json.dump(r, open(os.path.join(HERE, f'eval_{mode}.json'), 'w'), indent=1, ensure_ascii=False)
        log(json.dumps(r, ensure_ascii=False))
    else:
        final, calib, prior, oof = train_subject_model(lab, log)
        data_sha = hashlib.sha256(open(DATA_XLSX, 'rb').read()).hexdigest()
        bundle = assemble_bundle(final, calib, prior, fallback, v26, {
            'trained_on': {'source_file': 'journals_classified_v2.6.xlsx (sheet 2_Full_16768_Jurnal; asal: journals_export_20261105_161058_1.csv)',
                           'source_sha256': data_sha, 'n_journals': int(len(df)), 'n_labeled_subject': int(len(lab))},
            'oof_stats': oof, 'trained_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'lexicon_groups': sorted(svc.SUBJECT_LEXICON.keys()),
        })
        raw = pickle.dumps(bundle, protocol=pickle.HIGHEST_PROTOCOL)
        open(os.path.join(HERE, 'sclips_models_v2.7.pkl'), 'wb').write(raw)
        log(f'model disimpan: {len(raw)/1e6:.1f} MB, sha256 {hashlib.sha256(raw).hexdigest()}')


if __name__ == '__main__':
    main(sys.argv[1])

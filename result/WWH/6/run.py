"""用固定云库快照比较标签与已有属性对当前 Steam 好评率的预测能力。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupShuffleSplit
from sqlalchemy import text

from cleaning.db import get_engine

SEED = 42
ATTRIBUTES = ('valve_genres', 'valve_categories', 'developers', 'publishers')
MODEL_NAMES = ('mean', 'median', 'tags_ridge', 'attributes_ridge', 'attributes_trees')


def extract_snapshot(output: Path) -> Path:
    """读取一致性快照并登记内容指纹，不修改业务数据或结构。"""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            conn.execute(text("SET LOCAL statement_timeout='30s'"))
            rows = [dict(r._mapping) for r in conn.execute(text("""
                SELECT g.appid, g.name_en, g.name_zh, s.positive, s.negative,
                       s.fetched_at AS reviews_fetched_at,
                       COALESCE(a.release_date,b.release_date) AS release_date,
                       a.is_free,a.valve_genres,a.valve_categories,a.developers,a.publishers,
                       a.fetched_at AS attributes_fetched_at
                FROM games g JOIN steamspy_games s USING(appid)
                JOIN steam_appdetails a USING(appid)
                LEFT JOIN store_search_games b USING(appid)
                WHERE s.positive>=0 AND s.negative>=0
                  AND s.positive::bigint+s.negative>=100 AND a.type='game'
                  AND COALESCE(a.release_date,b.release_date) < DATE '2026-01-01'
                  AND NOT EXISTS (SELECT 1 FROM mapping_issues m
                                  WHERE m.appid=g.appid AND NOT m.resolved)
                ORDER BY g.appid
            """))]
            tags: dict[int, list[str]] = {}
            if not rows:
                raise ValueError('没有符合评价数和发售日期条件的游戏')
            for r in conn.execute(text("""
                SELECT appid,tag FROM game_tags
                WHERE source='steamspy' AND kind='theme' AND votes>0
                  AND appid=ANY(:ids)
                ORDER BY appid,votes DESC,tag
            """), {'ids': [r['appid'] for r in rows]}):
                values = tags.setdefault(r.appid, [])
                if len(values) < 20:
                    values.append(r.tag)
            before_tags = len(rows)
            rows = [dict(r, tags=tags[r['appid']]) for r in rows if r['appid'] in tags]
        payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode()
        digest = hashlib.sha256(payload).hexdigest()
        version = f'reputation-{date.today():%Y%m%d}-{digest[:12]}'
        meta = {
            'version': version, 'sha256': digest,
            'extracted_at': datetime.now(timezone.utc).isoformat(),
            'rows_before_tag_filter': before_tags, 'rows': len(rows),
            'filters': 'SteamSpy reviews>=100; appdetails type=game; release<2026; no unresolved mapping issue; positive-vote SteamSpy theme tags',
            'tag_timestamp': 'not available in game_tags',
        }
        path = output / f'{version}.snapshot.json'
        path.write_text(json.dumps({'meta': meta, 'rows': rows}, ensure_ascii=False,
                                   sort_keys=True, default=str), encoding='utf-8')
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL statement_timeout='10s'"))
            conn.execute(text("SET LOCAL lock_timeout='2s'"))
            conn.execute(text("""
                INSERT INTO dataset_versions(version,note) VALUES(:version,:note)
                ON CONFLICT(version) DO NOTHING
            """), {'version': version, 'note': json.dumps(meta, ensure_ascii=False)})
        return path
    finally:
        engine.dispose()


def title_group(row: dict[str, Any]) -> str:
    """规范化标题用于分组；不能保证识别不同命名的同游戏版本。"""
    title = row['name_en'] or row['name_zh'] or str(row['appid'])
    return re.sub(r'[^\w]+', '', title.casefold().replace('®', '').replace('™', ''))


def features(row: dict[str, Any], attributes: bool) -> dict[str, float]:
    """构造白名单特征，不读取评价量、评分或行为结果。"""
    values = {f'tag:{tag}': 1.0 for tag in row['tags']}
    if attributes:
        values['numeric:release_year'] = (int(row['release_date'][:4]) - 2010) / 10
        values[f'free:{row["is_free"]}'] = 1.0
        for name in ATTRIBUTES:
            tokens = row.get(name) or []
            if not tokens:
                values[f'missing:{name}'] = 1.0
            for token in tokens:
                values[f'{name}:{token}'] = 1.0
    return values


def encode(train: list[dict[str, Any]], other: list[dict[str, Any]],
           attributes: bool) -> tuple[Any, Any, DictVectorizer, set[str]]:
    """仅用训练集建立出现至少十次的类别词表。"""
    raw = [features(r, attributes) for r in train]
    counts = Counter(key for row in raw for key in row if not key.startswith('numeric:'))
    allowed = {key for key, count in counts.items() if count >= 10}
    allowed.update(key for row in raw for key in row if key.startswith('numeric:'))
    vectorizer = DictVectorizer(dtype=np.float32)
    xtrain = vectorizer.fit_transform([{k: v for k, v in r.items() if k in allowed} for r in raw])
    xother = vectorizer.transform([{k: v for k, v in features(r, attributes).items() if k in allowed}
                                  for r in other])
    # 新版 SciPy 可返回 int64 索引，sklearn 树模型预测要求 int32。
    for matrix in (xtrain, xother):
        matrix.indices = matrix.indices.astype(np.int32)
        matrix.indptr = matrix.indptr.astype(np.int32)
    return xtrain, xother, vectorizer, allowed


def metrics(y: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    """以百分点为单位计算每款游戏等权的误差。"""
    if not len(y):
        return {'n': 0, 'mae': None, 'rmse': None, 'r2': None}
    return {'n': len(y), 'mae': float(mean_absolute_error(y, prediction)),
            'rmse': float(math.sqrt(mean_squared_error(y, prediction))),
            'r2': float(r2_score(y, prediction)) if len(y)>1 else None}


def grouped_split(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    """按规范化标题分组，以固定种子留出百分之二十。"""
    return next(GroupShuffleSplit(n_splits=1, test_size=.2, random_state=SEED).split(
        rows, groups=[title_group(r) for r in rows]))


def evaluate(rows: list[dict[str, Any]], train_ids: np.ndarray, test_ids: np.ndarray,
             name: str, folder: Path) -> dict[str, Any]:
    """在预定留出集评价模型与两种常数对照；Ridge 在训练集内部选 alpha。"""
    train = [rows[i] for i in train_ids]
    test = [rows[i] for i in test_ids]
    if len(train)<100 or len(test)<100:
        raise ValueError(f'{name}: 留出集或训练集少于100款')
    assert not ({title_group(r) for r in train} & {title_group(r) for r in test})
    target = lambda values: np.array([100*r['positive']/(r['positive']+r['negative']) for r in values])
    ytrain, ytest = target(train), target(test)
    fit_ids, val_ids = grouped_split(train)
    inner_train = [train[i] for i in fit_ids]
    inner_val = [train[i] for i in val_ids]
    seen_devs = {d.casefold() for r in train for d in (r['developers'] or [])}
    known = np.array([any(d.casefold() in seen_devs for d in r['developers'] or []) for r in test])
    unknown = np.array([bool(r['developers']) for r in test]) & ~known
    high_reviews = np.array([r['positive']+r['negative']>=1000 for r in test])
    results: dict[str, Any] = {'train_n': len(train), 'test_n': len(test), 'models': {}}
    predictions = pd.DataFrame({'appid': [r['appid'] for r in test],
                                'name': [r['name_en'] or r['name_zh'] for r in test],
                                'actual_percent': ytest,
                                'reviews': [r['positive']+r['negative'] for r in test]})
    for model_name in MODEL_NAMES:
        print(f'{name}: fitting {model_name}', flush=True)
        params: dict[str, Any] = {}
        artifact: dict[str, Any] = {'clip': [0, 100], 'seed': SEED, 'dataset_version': folder.name}
        if model_name in ('mean', 'median'):
            model = DummyRegressor(strategy=model_name)
            model.fit(np.zeros((len(train), 1)), ytrain)
            prediction = model.predict(np.zeros((len(test), 1)))
        else:
            attributes = model_name != 'tags_ridge'
            xtrain, xtest, vectorizer, allowed = encode(train, test, attributes)
            if model_name.endswith('ridge'):
                xi, xv, _, _ = encode(inner_train, inner_val, attributes)
                validation = {}
                for alpha in (1., 10., 100.):
                    candidate = Ridge(alpha=alpha, solver='lsqr', tol=1e-6)
                    candidate.fit(xi, ytrain[fit_ids])
                    validation[alpha] = float(mean_absolute_error(ytrain[val_ids],
                                                        np.clip(candidate.predict(xv), 0, 100)))
                alpha = min(validation, key=validation.get)
                model = Ridge(alpha=alpha, solver='lsqr', tol=1e-6)
                params = {'alpha': alpha, 'validation_mae': validation}
            else:
                params = {'n_estimators': 200, 'min_samples_leaf': 5,
                          'max_depth': 24, 'max_features': .7, 'random_state': SEED, 'n_jobs': 2}
                model = ExtraTreesRegressor(**params)
            model.fit(xtrain, ytrain)
            prediction = np.clip(model.predict(xtest), 0, 100)
            artifact.update(vectorizer=vectorizer, allowed=allowed, attributes=attributes)
            params['n_features'] = xtrain.shape[1]
        results['models'][model_name] = {
            **metrics(ytest, prediction), 'parameters': params,
            'reviews_ge1000': metrics(ytest[high_reviews], prediction[high_reviews]),
            'known_developer': metrics(ytest[known], prediction[known]),
            'unseen_developer': metrics(ytest[unknown], prediction[unknown]),
        }
        predictions[model_name] = prediction
        artifact['model'] = model
        joblib.dump(artifact, folder / f'{name}-{model_name}.joblib')
    for result in results['models'].values():
        for baseline in ('mean', 'median'):
            error = results['models'][baseline]['mae']
            result[f'mae_improvement_vs_{baseline}_percent'] = 100*(error-result['mae'])/error
    predictions.to_csv(folder / f'{name}-predictions.csv', index=False)
    return results


def main() -> None:
    """提取或重放固定快照，保存指标、模型和逐游戏留出预测。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, help='已有固定快照；指定后完全不连接云库')
    parser.add_argument('--output', type=Path, default=ROOT/'data/processed/wwh6')
    parser.add_argument('--predict-appid', type=int, help='用已保存模型预测快照中的一款游戏，不重新训练')
    parser.add_argument('--split', choices=('random', 'release_cohort'), default='random')
    parser.add_argument('--model', choices=MODEL_NAMES, default='attributes_ridge')
    args = parser.parse_args()
    if args.predict_appid is not None and args.snapshot is None:
        parser.error('--predict-appid 必须同时指定 --snapshot')
    args.output.mkdir(parents=True, exist_ok=True)
    snapshot = args.snapshot or extract_snapshot(args.output)
    document = json.loads(snapshot.read_text(encoding='utf-8'))
    rows, meta = document['rows'], document['meta']
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if digest != meta['sha256']:
        raise ValueError('固定快照 SHA256 不匹配')
    folder = args.output / meta['version']
    folder.mkdir(parents=True, exist_ok=True)
    train, test = grouped_split(rows)
    recent = np.array([i for i,r in enumerate(rows) if int(r['release_date'][:4])>=2023])
    recent_titles = {title_group(rows[i]) for i in recent}
    old = np.array([i for i,r in enumerate(rows) if int(r['release_date'][:4])<=2022
                    and title_group(r) not in recent_titles])
    splits = {'random': (train, test), 'release_cohort': (old, recent)}
    if args.predict_appid is not None:
        index = next((i for i,r in enumerate(rows) if r['appid']==args.predict_appid), None)
        if index is None:
            raise ValueError('该 appid 不在固定快照中；不会自动补采')
        row = rows[index]
        artifact = joblib.load(folder/f'{args.split}-{args.model}.joblib')
        if artifact['dataset_version'] != meta['version']:
            raise ValueError('模型与固定快照版本不一致')
        if args.model in ('mean', 'median'):
            matrix = np.zeros((1, 1))
        else:
            raw = {k:v for k,v in features(row, artifact['attributes']).items() if k in artifact['allowed']}
            matrix = artifact['vectorizer'].transform([raw])
            matrix.indices = matrix.indices.astype(np.int32)
            matrix.indptr = matrix.indptr.astype(np.int32)
        prediction = float(np.clip(artifact['model'].predict(matrix)[0], 0, 100))
        print(json.dumps({'version': meta['version'], 'appid': row['appid'], 'name': row['name_en'],
                          'model': args.model, 'split': args.split,
                          'membership': 'held_out' if index in splits[args.split][1] else
                                        'training' if index in splits[args.split][0] else 'excluded',
                          'predicted_percent': prediction,
                          'snapshot_actual_percent': 100*row['positive']/(row['positive']+row['negative'])},
                         ensure_ascii=False, indent=2))
        return
    summary: dict[str, Any] = {
        'meta': meta, 'snapshot': str(snapshot.resolve()), 'seed': SEED,
        'software': {'python': sys.version.split()[0], 'sklearn': sklearn.__version__,
                     'numpy': np.__version__, 'pandas': pd.__version__},
        'sample': {'n': len(rows), 'unique_title_groups': len({title_group(r) for r in rows}),
                   'median_reviews': float(np.median([r['positive']+r['negative'] for r in rows])),
                   'reviews_fetched_range': [min(r['reviews_fetched_at'] for r in rows), max(r['reviews_fetched_at'] for r in rows)],
                   'attributes_fetched_range': [min(r['attributes_fetched_at'] for r in rows), max(r['attributes_fetched_at'] for r in rows)],
                   'missing': {k: sum(not r.get(k) for r in rows) for k in ATTRIBUTES}},
        'splits': {},
    }
    for name, (tr, te) in splits.items():
        summary['splits'][name] = evaluate(rows, tr, te, name, folder)
    (folder/'metrics.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"version={meta['version']} rows={len(rows)} output={folder}")
    for split, result in summary['splits'].items():
        print(f"{split}: train={result['train_n']} test={result['test_n']}")
        for name, scores in result['models'].items():
            print(f"  {name}: MAE={scores['mae']:.4f} RMSE={scores['rmse']:.4f} R2={scores['r2']:.4f}")


if __name__ == '__main__':
    main()

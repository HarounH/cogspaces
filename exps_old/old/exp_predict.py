from os.path import join

import numpy as np
import pandas as pd
from cogspaces.models.trace import TraceClassifier
from cogspaces.pipeline import get_output_dir, make_data_frame, split_folds, \
    MultiDatasetTransformer
from joblib import load
from sacred import Experiment
from sacred.observers import FileStorageObserver
from scipy.linalg import svd
from sklearn.externals.joblib import dump

idx = pd.IndexSlice

exp = Experiment('predict')
basedir = join(get_output_dir(), 'predict')
exp.observers.append(FileStorageObserver.create(basedir=basedir))


@exp.config
def config():
    datasets = ['archi']
    reduced_dir = join(get_output_dir(), 'reduced')
    unmask_dir = join(get_output_dir(), 'unmasked')
    source = 'hcp_rs_concat'
    test_size = {'hcp': .1, 'archi': .5, 'brainomics': .5, 'camcan': .5,
                 'la5c': .5, 'full': .5}
    train_size = dict(hcp=None, archi=None, la5c=None, brainomics=None,
                      camcan=None,
                      human_voice=None)
    dataset_weights = {'brainomics': 1, 'archi': 1, 'hcp': 1}
    model = 'trace'
    alpha = 1e-2
    max_iter = 1000
    verbose = 10
    seed = 10

    with_std = True
    with_mean = True
    per_dataset = False
    split_loss = True

    # Factored only
    n_components = 200
    latent_dropout_rate = 0.
    input_dropout_rate = 0.
    batch_size = 128
    optimizer = 'adam'
    step_size = 1e-3


@exp.capture
def fit_model(df_train, df_test, dataset_weights, model, alpha,
              n_components,
              per_dataset,
              batch_size,
              with_std, with_mean,
              split_loss,
              optimizer, latent_dropout_rate, input_dropout_rate,
              step_size, max_iter, verbose, _run):
    transformer = MultiDatasetTransformer(with_std=with_std,
                                          with_mean=with_mean,
                                          integer_coding=model in ['factored',
                                                                   'logistic'],
                                          per_dataset=per_dataset)
    transformer.fit(df_train)
    Xs_train, ys_train = transformer.transform(df_train)
    datasets = df_train.index.get_level_values('dataset').unique().values

    dataset_weights_list = []
    for dataset in datasets:
        if dataset in dataset_weights:
            dataset_weights_list.append(dataset_weights[dataset])
        else:
            dataset_weights_list.append(1.)
    dataset_weights = dataset_weights_list
    Xs_test, ys_test = transformer.transform(df_test)
    if model == 'trace':
        estimator = TraceClassifier(trace_penalty=alpha,
                                    step_size_multiplier=1000,
                                    fit_intercept=True,
                                    max_backtracking_iter=10,
                                    momentum=True,
                                    split_loss=split_loss,
                                    l2_penalty=0,
                                    max_iter=max_iter,
                                    verbose=verbose)
    elif model == 'logistic':
        from cogspaces.model.non_convex_pytorch import NonConvexEstimator
        estimator = NonConvexEstimator(
            alpha=alpha, n_components=n_components,
            architecture='flat',
            latent_dropout_rate=latent_dropout_rate,
            input_dropout_rate=input_dropout_rate,
            batch_size=batch_size,
            optimizer=optimizer,
            max_iter=max_iter,
            step_size=step_size)
    elif model == 'factored':
        from cogspaces.model.non_convex_pytorch import NonConvexEstimator
        estimator = NonConvexEstimator(
            alpha=alpha, n_components=n_components,
            architecture='factored',
            latent_dropout_rate=latent_dropout_rate,
            input_dropout_rate=input_dropout_rate,
            batch_size=batch_size,
            optimizer=optimizer,
            max_iter=max_iter,
            step_size=step_size)
    elif model == 'factored_keras':
        from cogspaces.model.non_convex_keras import NonConvexEstimator
        estimator = NonConvexEstimator(
            alpha=alpha, n_components=n_components,
            latent_dropout_rate=latent_dropout_rate,
            input_dropout_rate=input_dropout_rate,
            batch_size=batch_size,
            max_iter=max_iter,
            step_size=step_size)
    else:
        raise ValueError('Wrong model argument')
    estimator.fit(Xs_train, ys_train, study_weights=dataset_weights)
    ys_pred_train = estimator.predict(Xs_train)
    pred_df_train = transformer.inverse_transform(df_train, ys_pred_train)
    ys_pred_test = estimator.predict(Xs_test)
    pred_df_test = transformer.inverse_transform(df_test, ys_pred_test)

    return pred_df_train, pred_df_test, estimator, transformer


@exp.automain
def main(datasets, source, reduced_dir, unmask_dir,
         test_size, train_size,
         _run, _seed):
    artifact_dir = join(_run.observers[0].basedir, str(_run._id))
    single = False
    if source in ['hcp_rs_positive_single', 'initial_reduction']:
        source = 'hcp_rs_positive'
        single = True
    df = make_data_frame(datasets, source,
                         reduced_dir=reduced_dir,
                         unmask_dir=unmask_dir)
    if single:
        df = df.iloc[:, -512:]
    if source == 'initial_reduction':
        estimator = load(join(get_output_dir(), 'estimator.pkl'))
        coef = estimator.coef_
        U, S, VT = svd(coef)
        rank = 41
        U = U[:, :rank]
        projected_df = df.values[:, -512:].dot(coef)
        df = pd.DataFrame(data=projected_df, index=df.index)
    df_train, df_test = split_folds(df, test_size=test_size,
                                    train_size=train_size,
                                    random_state=_seed)
    pred_df_train, pred_df_test, estimator, transformer \
        = fit_model(df_train, df_test,
                    )

    pred_contrasts = pd.concat([pred_df_test, pred_df_train],
                               keys=['test', 'train'],
                               names=['fold'], axis=0)
    true_contrasts = pred_contrasts.index.get_level_values('contrast').values
    res = pd.DataFrame({'pred_contrast': pred_contrasts,
                        'true_contrast': true_contrasts})
    res.to_csv(join(artifact_dir, 'prediction.csv'))
    match = res['pred_contrast'] == res['true_contrast']
    score = match.groupby(level=['fold', 'dataset']).aggregate('mean')
    score_mean = match.groupby(level=['fold']).aggregate('mean')

    score_dict = {}
    for fold, this_score in score_mean.iteritems():
        score_dict['%s_mean' % fold] = this_score
    for (fold, dataset), this_score in score.iteritems():
        score_dict['%s_%s' % (fold, dataset)] = this_score
    _run.info['score'] = score_dict

    rank = np.linalg.matrix_rank(estimator.coef_)
    try:
        dump(estimator, join(artifact_dir, 'estimator.pkl'))
    except TypeError:
        pass
    _run.info['rank'] = rank
    dump(transformer, join(artifact_dir, 'transformer.pkl'))
    print('rank', rank)
    print(score)
    print(score_mean)

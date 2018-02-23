
import os
import sys
from copy import copy
from os import path
from os.path import join

import numpy as np
from cogspaces.pipeline import get_output_dir
from sacred import Experiment
from sacred.observers import FileStorageObserver
from sklearn.externals.joblib import Parallel
from sklearn.externals.joblib import delayed
from sklearn.utils import check_random_state

print(path.dirname(path.dirname(path.abspath(__file__))))
# Add examples to known models
sys.path.append(
    path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))
from exps_old.pipelining.decompose import exp as single_exp

exp = Experiment('multi_decompose')
basedir = join(get_output_dir(), 'multi_decompose')
if not os.path.exists(basedir):
    os.makedirs(basedir)
exp.observers.append(FileStorageObserver.create(basedir=basedir))


@exp.config
def config():
    n_jobs = 7
    seed = 1000


@single_exp.config
def config():
    n_components = 128
    batch_size = 200
    learning_rate = 0.92
    method = 'masked'
    reduction = 12
    alpha = 1e-4
    n_epochs = 1
    verbose = 15
    n_jobs = 1
    smoothing_fwhm = 4
    positive = True


def single_run(config_updates, rundir, _id):
    run = single_exp._create_run(config_updates=config_updates)
    observer = FileStorageObserver.create(basedir=rundir)
    run._id = _id
    run.observers = [observer]
    run()


@exp.automain
def run(n_jobs, _run, _seed):
    random_state = check_random_state(_seed)
    exps = []
    for n_components in [208]:
        for alpha in np.logspace(-5, -2, 7):
            seed = random_state.randint(np.iinfo(np.uint32).max)
            exps.append(dict(n_components=n_components, alpha=alpha, seed=seed))
    rundir = join(basedir, str(_run._id), 'run')
    if not os.path.exists(rundir):
        os.makedirs(rundir)

    Parallel(n_jobs=n_jobs,
             verbose=10)(delayed(single_run)(config_updates, rundir, i)
                         for i, config_updates in enumerate(exps))

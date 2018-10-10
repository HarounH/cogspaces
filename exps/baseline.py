import os
from os.path import join

from cogspaces.classification.logistic import MultiLogisticClassifier
from cogspaces.datasets import STUDY_LIST, load_reduced_loadings
from cogspaces.datasets.contrast import load_masked_contrasts
from cogspaces.model_selection import train_test_split
from cogspaces.plotting.volume import plot_4d_image
from cogspaces.preprocessing import MultiStandardScaler, MultiTargetEncoder
from cogspaces.report import save
from cogspaces.utils import compute_metrics

# Parameters
system = dict(
    verbose=1,
    n_jobs=3,
    seed=860
)
data = dict(
    studies=['archi', 'hcp'],
    test_size=0.5,
    train_size=0.5,
    reduced=True,
    data_dir=None,
)
model = dict(
    estimator='factored',
    normalize=False,
    seed=100,
    target_study=None,
)

logistic = dict(
    estimator='logistic',
    l2_penalty=[7e-5],
    max_iter=1000,
    )

config = {'system': system, 'data': data, 'model': model, 'logistic': logistic}

output_dir = join('output', 'baseline')
if not os.path.exists(output_dir):
    os.makedirs(output_dir)
info = {}

# Load data
if data['studies'] == 'all':
    studies = STUDY_LIST
elif isinstance(data['studies'], str):
    studies = [data['studies']]
elif isinstance(data['studies'], list):
    studies = data['studies']
else:
    raise ValueError("Studies should be a list or 'all'")

if data['reduced']:
    input_data, target = load_reduced_loadings(data_dir=data['data_dir'])
else:
    input_data, target = load_masked_contrasts(data_dir=data['data_dir'])

input_data = {study: input_data[study] for study in studies}
target = {study: target[study] for study in studies}

target_encoder = MultiTargetEncoder().fit(target)
target = target_encoder.transform(target)

train_data, test_data, train_targets, test_targets = \
    train_test_split(input_data, target, random_state=system['seed'],
                     test_size=data['test_size'],
                     train_size=data['train_size'])


# Train
if model['normalize']:
    standard_scaler = MultiStandardScaler().fit(train_data)
    train_data = standard_scaler.transform(train_data)
    test_data = standard_scaler.transform(test_data)
else:
    standard_scaler = None

estimator = MultiLogisticClassifier(verbose=system['verbose'], **logistic)
estimator.fit(train_data, train_targets)

# Estimate
test_preds = estimator.predict(test_data)
metrics = compute_metrics(test_preds, test_targets, target_encoder)

# Save model for further analysis
save(target_encoder, standard_scaler, estimator, metrics, info, config, output_dir,
     estimator_type='logistic')

# Plot
classifs_imgs = join(output_dir, 'classifs.nii.gz')
full_names = join(output_dir, 'full_names.pkl')

plot_4d_image(classifs_imgs,
              output_dir=join(output_dir, 'classifs'),
              names=full_names,
              view_types=['stat_map', 'glass_brain'], threshold=0,
              n_jobs=system['n_jobs'])
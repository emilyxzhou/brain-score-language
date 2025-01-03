# Include the following lines at the top of each file for file pathing.
import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../..')) # adjust relative path as needed
import file_utils

import numpy as np
import os
import pandas as pd
import scipy
import sys
import xarray as xr
import pdb
from tqdm import tqdm
import json

from brainio.assemblies import DataAssembly, NeuroidAssembly
from brainscore_core.benchmarks import BenchmarkBase
from brainscore_core.metrics import Score, Metric

from brainscore_language import load_dataset, load_metric
from brainscore_language.artificial_subject import ArtificialSubject
from brainscore_language.utils.ceiling import ceiling_normalize
from brainscore_language import benchmark_registry
from brainscore_language.metrics.neural_cosine_similarity.metric import NeuralCosineSimilarity

from scipy.stats import pearsonr


def _build_id(assembly, coords):
    ids =  [".".join([f"{value}" for value in values]) for values in zip(*[assembly[coord].values for coord in coords])]
    return ids


def _build_id_from_subjects_and_voxels(voxel_subjects, voxel_nums):
    ids = [f"{voxel_subjects[i]}.{voxel_nums[i]}" for i in range(len(voxel_subjects))]
    return ids


class GermanEmotiveIdioms(BenchmarkBase):

    def __init__(self, neural_data, num_subjects, selected_stimuli_ids, ceiling, metric=None):
        
        self.load_data_into_assembly(neural_data, num_subjects, selected_stimuli_ids)

        if metric is None:
            self.metric = load_metric('linear_pearsonr_unaveraged')
        else:
            self.metric = metric

        super(GermanEmotiveIdioms, self).__init__(
            identifier="GermanEmotiveIdioms",
            version=1,
            parent='GermanEmotiveIdioms',
            ceiling=ceiling
        )
        
    def load_data_into_assembly(self, neural_data, num_subjects, selected_stimuli_ids):
        """
        Loads a numpy array into a Neuroid Assembly (https://github.com/brain-score/brainio/blob/main/brainio/assemblies.py).
        A Neuroid Assembly is just a wrapper for an XArray, which itself is basically a numpy array with metadata.
        For code compatability, the dimensions MUST be named exactly "presentation" and "neuroid",
        which correspond to the stimulus row and the neuron activation score column.
        """
        assert neural_data.shape[1] % num_subjects == 0, 'Unequal number of voxels per subject'
        voxels_per_subject = neural_data.shape[1] // num_subjects
        
        stimuli_file = os.path.join(file_utils.IDIOMS_DATA_PROCESSING_PATH, "stimuli.tsv")
        
        stimuli = pd.read_csv(stimuli_file, sep='\t', encoding='utf-8')
        selected_stimuli = stimuli[stimuli['Code'].isin(selected_stimuli_ids)]
        sentences = selected_stimuli["Stimulus"].to_numpy().tolist()
        # sentences = selected_stimuli["Translation"].to_numpy().tolist() # try English translation
        
        # seleted stimuli and provided neural data should be the same size
        assert neural_data.shape[0] == len(selected_stimuli_ids)
        # create two lists of length (num_subjects * voxels_per_subject)
        # voxel_subjects refers to the subject number, voxel_nums refers to the voxel number within a subject
        # i.e., if there are 20 subjects and 400 voxels per subject, index 500 will have voxel_subject=2 and voxel_nums=100
        voxel_subjects = []
        voxel_nums = []
        for i in range(1, num_subjects + 1):
            voxel_subjects.extend([str(i)] * voxels_per_subject)
            voxel_nums.extend(list(range(voxels_per_subject)))
        
        neuroid_ids = _build_id_from_subjects_and_voxels(voxel_subjects, voxel_nums)
        data = NeuroidAssembly(
            neural_data, 
            coords={
                'stimulus_num': ('presentation', selected_stimuli_ids),
                'stimulus_id': ('presentation', [str(i) for i in selected_stimuli_ids]),
                'sentence': ('presentation', sentences),
                'stimulus': ('presentation', sentences),
                'subject': ('neuroid', voxel_subjects),
                'voxel_num': ('neuroid', voxel_nums),
                'neuroid_id': ('neuroid', neuroid_ids)
            },
            dims=['presentation', 'neuroid']
        )

        data.name = 'data'
        data.attrs['identifier'] = 'german_emotive_idioms'
        self.data = data
        

    def __call__(self, candidate: ArtificialSubject, train_regression=True) -> Score:
        candidate.start_neural_recording(
            recording_target=ArtificialSubject.RecordingTarget.language_system,
            recording_type=ArtificialSubject.RecordingType.fMRI
        )
        stimuli = self.data['stimulus']
        predictions = candidate.digest_text(stimuli.values)['neural']
        predictions['stimulus_id'] = 'presentation', stimuli['stimulus_id'].values

        actual = self.data
        
        raw_score = self.metric(predictions, actual, train_regression=train_regression)
        # score = ceiling_normalize(raw_score, self.ceiling)
        score = [raw / self.ceiling.item() for raw in raw_score]
        return score
                
    
                
            
    
# ----------------------------------------------------------------------------------------------------
# Additional metric definitions
from sklearn.cross_decomposition import CCA
from sklearn.decomposition import TruncatedSVD


def rsm(activity_matrix):
    """
    Compute the Representational Similarity Matrix (RSM).
    RSM is defined as the dot product of the centered activity matrix with itself.
    :param activity_matrix: 2D numpy array of shape (n_stimuli, n_features)
    :return: RSM of shape (n_stimuli, n_stimuli)
    """
    # Center the activity matrix
    activity_centered = activity_matrix - np.mean(activity_matrix, axis=0, keepdims=True)
    # Compute the RSM as the dot product of the centered matrix
    rsm = np.dot(activity_centered, activity_centered.T)
    return rsm


def rsa(model_activity, brain_activity):
    """
    Perform Representational Similarity Analysis between model and brain RDMs.
    :param model_activity: 2D numpy array of shape (n_stimuli, n_features) for model
    :param brain_activity: 2D numpy array of shape (n_stimuli, n_features) for brain
    :return: RSA score (correlation between model RDM and brain RDM)
    """
    model_rdm = rdm(model_activity)
    brain_rdm = rdm(brain_activity)

    # Flatten the RDMs and compute their correlation
    model_rdm_flat = model_rdm[np.triu_indices_from(model_rdm, k=1)]
    brain_rdm_flat = brain_rdm[np.triu_indices_from(brain_rdm, k=1)]
    rsa_score, _ = scipy.stats.pearsonr(model_rdm_flat, brain_rdm_flat)
    
    return rsa_score


def cka(rsm1, rsm2):
    """
    Compute the Centered Kernel Alignment (CKA) score between two RSMs.
    :param rsm1: RSM from the ANN of shape (n_stimuli, n_stimuli)
    :param rsm2: RSM from the brain data of shape (n_stimuli, n_stimuli)
    :return: CKA similarity score
    """
    # Compute the normalized inner product
    numerator = np.sum(rsm1 * rsm2)
    denominator = np.sqrt(np.sum(rsm1 * rsm1) * np.sum(rsm2 * rsm2))
    cka_score = numerator / denominator
    return cka_score


def svcca(data1, data2, svd_components=None):
    """
    Perform Singular Vector Canonical Correlation Analysis (SVCCA).
    :param data1: 2D numpy array (n_samples, n_features1) representing ANN activations.
    :param data2: 2D numpy array (n_samples, n_features2) representing brain activity.
    :param svd_components: Number of components to retain for SVD. If None, retains all components.
    :return: SVCCA similarity score (average correlation across canonical dimensions).
    """
    # Step 1: Perform SVD to denoise and reduce dimensions
    svd1 = TruncatedSVD(n_components=svd_components if svd_components else min(data1.shape))
    svd2 = TruncatedSVD(n_components=svd_components if svd_components else min(data2.shape))
    reduced_data1 = svd1.fit_transform(data1)
    reduced_data2 = svd2.fit_transform(data2)

    # Step 2: Perform Canonical Correlation Analysis (CCA)
    cca = CCA(n_components=min(reduced_data1.shape[1], reduced_data2.shape[1]))
    cca_data1, cca_data2 = cca.fit_transform(reduced_data1, reduced_data2)

    # Step 3: Compute correlation for each canonical dimension
    correlations = [np.corrcoef(cca_data1[:, i], cca_data2[:, i])[0, 1] for i in range(cca_data1.shape[1])]

    # Return the average correlation as the SVCCA similarity score
    svcca_score = np.mean(correlations)
    return svcca_score


def rdm(activity_matrix):
    """
    Compute the Representational Dissimilarity Matrix (RDM).
    RDM is defined as 1 - correlation between every pair of stimulus representations.
    :param activity_matrix: 2D numpy array of shape (n_stimuli, n_features)
    :return: RDM of shape (n_stimuli, n_stimuli)
    """
    n_stimuli = activity_matrix.shape[0]
    rdm = np.zeros((n_stimuli, n_stimuli))
    for i in range(n_stimuli):
        for j in range(n_stimuli):
            if i != j:
                rdm[i, j] = 1 - scipy.stats.pearsonr(activity_matrix[i], activity_matrix[j])[0]
    return rdm

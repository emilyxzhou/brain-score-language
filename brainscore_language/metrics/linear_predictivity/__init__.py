from brainscore_language import metric_registry
from .metric import linear_pearsonr, linear_pearsonr_unaveraged

metric_registry['linear_pearsonr'] = linear_pearsonr
metric_registry['linear_pearsonr_unaveraged'] = linear_pearsonr_unaveraged

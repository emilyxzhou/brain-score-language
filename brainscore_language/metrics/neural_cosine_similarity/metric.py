from scipy.spatial.distance import cosine
from sklearn.linear_model import LinearRegression


class NeuralCosineSimilarity:

    def __call__(self, train_source, train_target, test_source, test_target):
        regression = LinearRegression()
        regression.fit(train_source, train_target)
        predictions = regression.predict(test_source)
        
        assert predictions.shape == test_target.shape
        
        similarities = []
        
        for i in range(predictions.shape[0]):
            similarity = 1 - cosine(predictions[i], test_target[i])
            similarities.append(similarity)
            
        return similarities

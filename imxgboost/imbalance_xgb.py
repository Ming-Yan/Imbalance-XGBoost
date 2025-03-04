from random import sample
import numpy as np
import xgboost as xgb
from imxgboost.weighted_loss import Weight_Binary_Cross_Entropy
from imxgboost.focal_loss import Focal_Binary_Loss
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, matthews_corrcoef
from sklearn.model_selection import train_test_split


def evalerror(preds, dtrain):
    labels = dtrain.get_label()
    # return a pair metric_name, result
    # since preds are margin(before logistic transformation, cutoff at 0)

    return 'error', float(sum(labels != (preds > 0.0))) / len(labels)


def two_class_encoding(flat_prediction):
    if len(np.shape(flat_prediction)) == 2:
        return flat_prediction
    else:
        # class 1 probability
        class_one_prob = 1.0 / (1.0 + np.exp(-flat_prediction))
        class_one_prob = np.reshape(class_one_prob, [-1, 1])
        # class 0 probability
        class_zero_prob = 1 - class_one_prob
        class_zero_prob = np.reshape(class_zero_prob, [-1, 1])
        # concatenate the probabilities to get the final prediction
        sigmoid_two_class_pred = np.concatenate((class_zero_prob, class_one_prob), axis=1)

        return sigmoid_two_class_pred


class imbalance_xgboost(BaseEstimator, ClassifierMixin):
    """Data in the form of [nData * nDim], where nDim stands for the number of features.
       This wrapper would provide a Xgboost interface with sklearn estimiator structure, which could be stacked in other Sk pipelines
    """

    def __init__(self, para_dict={'eval_metric':["logloss","auc"],
                'max_depth': 3,
                'eta': 0.05,
                }, num_round=500,special_objective=None, early_stopping_rounds=None, imbalance_alpha=None,
                 focal_gamma=None):
        """
        Parameters to initialize a Xgboost estimator
        :param num_round. The rounds we would like to iterate to train the model
        :param max_depth. The maximum depth of the classification boosting, need to be specified
        :param num_class. The number of classes for the classifier
        :param eta Step. Size shrinkage used in update to prevents overfitting
        :param verbosity. Set to '1' or '0' to determine if print the information during training. True is higly recommended
        :param objective_func. The objective function we would like to optimize
        :param eval_metric. The loss metrix. Note this is partially correlated to the objective function, and unfit loss function would lead to problematic loss
        :param booster. The booster to be usde, can be 'gbtree', 'gblinear' or 'dart'.
        :param imbalance_alpha. The \alpha value for imbalanced loss. Will make impact on '1' classes. Must have when special_objective 'weighted'
        :param focal_gamma. The \gamma value for focal loss. Must have when special_objective 'focal'
        """
        self.para_dict = para_dict
        self.eval_list = []
        self.boosting_model = 0
        self.special_objective = special_objective
        self.early_stopping_rounds = early_stopping_rounds
        self.imbalance_alpha = imbalance_alpha
        self.focal_gamma = focal_gamma
        self.evals_result={}
        self.num_round= num_round
    def fit(self, data_x, data_y, sample_weight=None):
        if self.special_objective is None:
            # get the parameter list
            self.para_dict['objective'] = self.objective_func
        # else:
        #     # get the parameter list, without stating the objective function
        #     self.para_dict = {'max_depth': self.max_depth,
        #                       'eta': self.eta,
        #                       'verbosity': self.verbosity,
        #                       'eval_metric': self.eval_metric,
        #                       'booster': self.booster}
        # make sure data is in [nData * nSample] format
        # assert len(data_x.shape) == 2
        # check if data length is the same
        # if data_x.shape[0] != data_y.shape[0]:
        #     raise ValueError('The numbner of instances for x and y data should be the same!')
        # data_x is in [nData*nDim]
        # split the data into train and validation
        # indexing and get the data
        
        ### Improving train/test splitting
        X_train, X_test, y_train, y_test, w_train, w_test = train_test_split(data_x, data_y, sample_weight, test_size=0.5, random_state=42)
        # marixilize the data and train the estimator
        dtrain = xgb.DMatrix(X_train, label=y_train)
        dvalid = xgb.DMatrix(X_test, label=y_test)
        dtrain = xgb.DMatrix(X_train, label=y_train,weight=np.abs(w_train))
        dvalid = xgb.DMatrix(X_test, label=y_test,weight=np.abs(w_test))
        self.eval_list = [(dvalid, 'valid'), (dtrain, 'train')]
        # print(self.eval_list)
        if self.special_objective is None:
            # fit the classfifier
            self.boosting_model = xgb.train(self.para_dict,  dtrain,self.num_round, self.eval_list, verbose_eval=False, early_stopping_rounds=self.early_stopping_rounds,evals_result=self.evals_result)
        elif self.special_objective == 'weighted':
            # if the alpha value is None then raise an error
            if self.imbalance_alpha is None:
                raise ValueError('Argument imbalance_alpha must have a value when the objective is \'weighted\'!')
            # construct the object with imbalanced alpha value
            weighted_loss_obj = Weight_Binary_Cross_Entropy(imbalance_alpha=self.imbalance_alpha)
            # fit the classfifier
            self.boosting_model = xgb.train(self.para_dict, dtrain,  self.num_round,self.eval_list,
                                            obj=weighted_loss_obj.weighted_binary_cross_entropy, feval=evalerror,
                                            verbose_eval=False, early_stopping_rounds=self.early_stopping_rounds,evals_result=self.evals_result)
        elif self.special_objective == 'focal':
            # if the gamma value is None then raise an error
            if self.focal_gamma is None:
                raise ValueError('Argument focal_gamma must have a value when the objective is \'focal\'!')
            # construct the object with focal gamma value
            focal_loss_obj = Focal_Binary_Loss(gamma_indct=self.focal_gamma)
            # fit the classfifier
            # print(self.para_dict)
            self.boosting_model = xgb.train(self.para_dict, dtrain, self.num_round,self.eval_list,
                                            obj=focal_loss_obj.focal_binary_object, feval=evalerror, verbose_eval=False, early_stopping_rounds=self.early_stopping_rounds,evals_result=self.evals_result)
        else:
            raise ValueError(
                'The input special objective mode not recognized! Could only be \'weighted\' or \'focal\', but got ' + str(
                    self.special_objective))

    def predict(self, data_x, y=None, sample_weight=None):
        # matrixilize
        if y is not None:
            try:
                dtest = xgb.DMatrix(data_x, label=y)
            except:
                raise ValueError('Test data invalid!')
        else:
            dtest = xgb.DMatrix(data_x)
        prediction_output = self.boosting_model.predict(dtest)

        return prediction_output

    def predict_sigmoid(self, data_x, y=None,sample_weight=None):
        # sigmoid output, for the prob = 1

        raw_output = self.predict(data_x, y,sample_weight=sample_weight)
        sigmoid_output = 1. / (1. + np.exp(-raw_output))

        return sigmoid_output

    def predict_determine(self, data_x, y=None,sample_weight=None):
        # deterministic output
        sigmoid_output = self.predict_sigmoid(data_x, y,sample_weight=sample_weight)
        prediction_output = np.round(sigmoid_output)

        return prediction_output

    def predict_two_class(self, data_x, y=None,sample_weight=None):
        # predict the probability of two classes
        prediction_output = two_class_encoding(self.predict(data_x, y,sample_weight=sample_weight))

        return prediction_output

    def score(self, X, y, sample_weight=None):
        label_pred = self.predict_determine(data_x=X,sample_weight=sample_weight)
        score_pred = accuracy_score(y_true=y, y_pred=label_pred,sample_weight=sample_weight)

        return score_pred

    def score_eval_func(self, y_true, y_pred, mode='accuracy',sample_weight=None):
        prob_pred = two_class_encoding(y_pred)
        label_pred = np.argmax(prob_pred, axis=1)
        if mode == 'accuracy':
            score_pred = accuracy_score(y_true=y_true, y_pred=label_pred,sample_weight=sample_weight)
        elif mode == 'precision':
            score_pred = precision_score(y_true=y_true, y_pred=label_pred,sample_weight=sample_weight)
        elif mode == 'recall':
            score_pred = recall_score(y_true=y_true, y_pred=label_pred,sample_weight=sample_weight)
        elif mode == 'f1':
            score_pred = f1_score(y_true=y_true, y_pred=label_pred,sample_weight=sample_weight)
        elif mode == 'MCC':
            score_pred = matthews_corrcoef(y_true=y_true, y_pred=label_pred,sample_weight=sample_weight)
        else:
            raise ValueError('Score function mode unrecognized! Must from one in the list '
                             '[\'accuracy\', \'precision\',\'recall\',\'f1\',\'MCC\']')

        return score_pred

    def correct_eval_func(self, y_true, y_pred, mode='TP',sample_weight=None):
        # get the predictions first
        prob_pred = two_class_encoding(y_pred,sample_weight)
        label_pred = np.argmax(prob_pred, axis=1)
        # logic-not for the tn predictions
        y_true_negative = np.logical_not(y_true)
        y_pred_negative = np.logical_not(label_pred)
        # return values based on cases
        if mode == 'TP':
            return np.sum(np.logical_and(y_true, label_pred))
        elif mode == 'TN':
            return np.sum(np.logical_and(y_true_negative, y_pred_negative))
        elif mode == 'FP':
            return np.sum(np.logical_and(y_true_negative, label_pred))
        elif mode == 'FN':
            return np.sum(np.logical_and(y_true, y_pred_negative))
        else:
            raise ValueError('Corrective evaluation mode not recognized! '
                             'Must be one of \'TP\', \'TN\', \'FP\', or \'FN\'')
    
   
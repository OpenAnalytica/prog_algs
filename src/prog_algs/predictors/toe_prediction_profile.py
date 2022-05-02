# Copyright © 2021 United States Government as represented by the Administrator of the National Aeronautics and Space Administration. All Rights Reserved.
import matplotlib.pyplot as plt
from collections import UserDict
from typing import Dict
import numpy as np

from prog_algs.uncertain_data import UncertainData 

class ToEPredictionProfile(UserDict):
    """
    Data structure for storing the result of multiple predictions, including time of prediction. This data structure can be treated as a dictionary of time of prediction to Time of Event (ToE) prediction. Iteration of this data structure is in order of increasing time of prediction
    """
    def add_prediction(self, time_of_prediction: float, toe_prediction: UncertainData):
        """Add a single prediction to the profile

        Args:
            time_of_prediction (float): Time that the prediction was made
            toe_prediction (UncertainData): Distribution of predicted ToEs
        """
        self[time_of_prediction] = toe_prediction

    # Functions below are defined to ensure that any iteration is in order of increasing time of prediction
    def __iter__(self):
        return iter(sorted(super(ToEPredictionProfile, self).__iter__()))

    def items(self):
        """
        Get iterators for the items (time_of_prediction, toe_prediction) of the prediction profile
        """
        return iter((k, self[k]) for k in self)

    def keys(self):
        """
        Get iterator for the keys (i.e., time_of_prediction) of the prediction profile
        """
        return sorted(super(ToEPredictionProfile, self).keys())

    def values(self):
        """
        Get iterator for the values (i.e., toe_prediction) of the prediction profile
        """
        return [self[k] for k in self.keys()]

    def alpha_lambda(self, ground_truth : Dict[str, float], lambda_value : float, alpha : float, beta : float, **kwargs) -> Dict[str, bool]:
        """Calculate Alpha lambda metric for the prediction profile

        Args:
            ground_truth (Dict[str, float]):
                Ground Truth time of event for each event (e.g., {'event1': 748, 'event2', 2233, ...})
            lambda_value (float):
                Prediction time at or after which metric is evaluated. Evaluation occurs at this time (if a prediction exists) or the next prediction following.
            alpha (float): 
                percentage bounds around time to event (where 0.2 allows 20% error TtE)
            beta (float):
                portion of prediction that must be within those bounds
            kwargs (optional, keyword arguments):
                configuration arguments. Accepted arge include: \n
                 * keys (list[string]): list of keys to use. If not provided, all keys are used.
                 * print (bool) : If True, print the results. Default is False.

        Returns:
            Dict[str, bool]: If alpha lambda was met for each key (e.g., {'event1': True, 'event2', False, ...})
        """
        from ..metrics import alpha_lambda
        return alpha_lambda(self, ground_truth, lambda_value, alpha, beta, **kwargs)

    def prognostic_horizon(self, criteria_eqn, ground_truth, **kwargs) -> Dict[str, float]:
        """
        Compute prognostic horizon metric, defined as the difference between a time ti, when the predictions meet specified performance criteria, and the time corresponding to the true Time of Event (ToE), for each event.
        PH = ToE - ti
        Args:
            toe_profile (ToEPredictionProfile): A profile of predictions, the combination of multiple predictions
            criteria_eqn (Callable function): A function (toe: UncertainData, ground_truth: dict[str, float]) -> dict[str, bool] calculating whether a prediction in ToEPredictionProfile meets some criteria. \n
                | Args: 
                |  * toe (UncertainData): A single prediction of Time of Event (ToE)
                |  * ground truth (dict[str, float]): Ground truth passed into prognostics_horizon
                | Returns: Map of event names to boolean representing if the event has been met. 
                |   e.g., {'event1': True, 'event2': False}
            ground_truth (dict): Dictionary containing ground truth; specified as key, value pairs for event and its value. E.g, {'event1': 47.3, 'event2': 52.1, 'event3': 46.1}
            kwargs (optional): configuration arguments. Accepted args include:
                * print (bool): Boolean specifying whether the prognostic horizon metric should be printed.

        Returns:
            dict: Dictionary containing prognostic horizon calculations (value) for each event (key). e.g., {'event1': 12.3, 'event2': 15.1}
        """
        from ..metrics import prognostic_horizon
        return prognostic_horizon(self, criteria_eqn, ground_truth, **kwargs)

    def plot(self, ground_truth : dict = None , alpha : float = None, print : bool = True) -> dict: # use ground truth, alpha if given,
        """Produce an alpha-beta plot depicting the TtE distribution by time of prediction.

        Args:
            ground_truth : dict = None
                Optional dictionary argument containing event and its respective ground truth value; none by default and plotted if specified
            alpha : float
                Optional alpha value; none by default and plotted if specified
            print : bool = True
                Optional bool value; specify whether to display generated plots or not
        Returns:
            dict
                Collection of generated matplotlib figures for each event in profile
        """
        result_figs = {}
        for t,v in self.items():
            for key in v.keys():
                if key not in result_figs:
                    # Prepare Figure for Plot
                    fig_window = plt.figure() # Create new figure for this event key
                    fig_sub = fig_window.subplots()
                    fig_sub.grid()
                    fig_sub.set_title(key+" Plot")
                    fig_sub.set_xlabel('Time of Prediction (s)') # time to prediction
                    fig_sub.set_ylabel('Time to Event (s)') # time to event
                    result_figs[key] = fig_window
                # Create scatter plot for this event
                samples = v.sample(100) # sample distribution (red scatter plot)
                samples = [e[key]-t for e in samples]
                result_figs[key].get_axes()[0].scatter([t]*len(samples), samples, color='red') # Adding single distribution of estimates

        if ground_truth: # If ground_truth is specified, add ground_truth to each event plot (green line)
            for key, val in ground_truth.items():
                gt_x = range(int(val))
                gt_y = range(int(val), 0, -1)
                result_figs[key].get_axes()[0].plot(gt_x, gt_y, color='green')
                if alpha: # if ground_truth and alpha are specified, add alpha bounds (faded green highlight)
                    result_figs[key].get_axes()[0].fill_between(gt_x, np.array(gt_y)*(1-alpha), np.array(gt_y)*(1+alpha), color='green', alpha=0.2)
                result_figs[key].get_axes()[0].set_xlim(0, val+1)

        if print: # Optionally not display plots and just return plot objects
            plt.show()
        return result_figs 
        

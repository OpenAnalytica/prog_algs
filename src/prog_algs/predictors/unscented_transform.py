# Copyright © 2021 United States Government as represented by the Administrator of the National Aeronautics and Space Administration.  All Rights Reserved.

from typing import Callable
from .prediction import Prediction, UnweightedSamplesPrediction, PredictionResults
from .predictor import Predictor
from numpy import diag, array, transpose
from copy import deepcopy
from math import isnan
from filterpy import kalman
from prog_algs.uncertain_data import MultivariateNormalDist


class LazyUTPrediction(Prediction):
    def __init__(self, state_prediction, sigma_fcn : Callable, ut_fcn : Callable, transform_fcn : Callable):
        self.times = state_prediction.times
        self.__states = state_prediction
        self.__data = None
        self.__sigma_fcn = sigma_fcn
        self.__transform = transform_fcn
        self.__ut_fcn = ut_fcn

    @property
    def data(self):
        if self.__data == None:
            self.__data = []
            # For each timepoint
            for i in range(len(self.times)):
                x = self.__states.snapshot(i)

                # Get Sigma points
                keys = x.keys()
                mean = [x.mean[key] for key in keys]  # Maintain ordering
                covar = x.cov
                sigma_pts = self.__sigma_fcn.sigma_points(mean, covar)
                
                # Apply Tranformation (e.g., output, event_state)
                sigma_pt_tranformed = [
                    self.__transform({key: value for key, value in zip(keys, sigma_pt)})
                    for sigma_pt in sigma_pts
                ]
                # result is [sigma_pt][ -> output/event_state (dict)]

                transformed_keys = sigma_pt_tranformed[0].keys()

                # Flatten 
                sigma_pt_tranformed = array([array(list(sigma_pt.values())) for sigma_pt in sigma_pt_tranformed]) # map -> array

                # Apply Unscented Transform to form output distribution
                mean, cov = self.__ut_fcn(sigma_pt_tranformed, self.__sigma_fcn.Wm, self.__sigma_fcn.Wc)
                self.__data.append(MultivariateNormalDist(transformed_keys, mean, cov))

        return self.__data


class UnscentedTransformPredictor(Predictor):
    """
    Class for performing model-based prediction using an unscented transform. 

    This class defines logic for performing model-based state prediction using sigma points and an unscented transform. The Unscented Transform Predictor propagates the sigma-points in the state-space in time domain until the event threshold is met. The step at which the i-th sigma point reaches the threshold is the step at which the i-th sigma point will be placed along the time dimension. By repeating the procedure for all sigma-points, we obtain the sigma-points defining the distribution of the time of event (ToE); for example, the End Of Life (EOL) event. The provided future loading equation is used to compute the inputs to the system at any given time point. 

    The following configuration parameters are supported (as kwargs in constructor or as parameters in predict method):

    Configuration Parameters
    ------------------------------
    alpha, beta, kappa: float
        UKF Scaling parameters. See: https://en.wikipedia.org/wiki/Kalman_filter#Unscented_Kalman_filter
    t0 : float
        Initial time at which prediction begins, e.g., 0
    dt : float
        Simulation step size (s), e.g., 0.1
    events : List[string]
        Events to predict (subset of model.events) e.g., ['event1', 'event2']
    horizon : float
        Prediction horizon (s)
    save_freq : float
        Frequency at which results are saved (s)
    save_pts : List[float]
        Any additional savepoints (s) e.g., [10.1, 22.5]

    Note
    ----    
    The resulting sigma-points along the time dimension are used to compute mean and covariance of the event time (ToE), under the hypothesis that the ToE distribution would also be well represented by a Gaussian. This is a strong assumption that likely cannot be satisfied for real systems with strong non-linear state propagation or nonlinear ToE curves. Therefore, the user should be cautious and verify that modeling the event time using a Gaussian distribution is satisfactory.
    """
    default_parameters = {
        'alpha': 1,
        'beta': 0,
        'kappa': -1,
        't0': 0,
        'dt': 0.5,
        'horizon': 1e99,
        'save_pts': [],
        'save_freq': 1e99
    }

    def __init__(self, model, **kwargs):
        super().__init__(model, **kwargs)

        self.model = model
        self.__input = None  # Input at an individual step. Note, this needs to be a member to pass between state_transition and predict

        # setup UKF
        num_states = model.n_states
        num_measurements = model.n_outputs

        if 'Q' not in self.parameters:
            # Default 
            self.parameters['Q'] = diag([1.0e-1 for i in range(num_states)])
        if 'R' not in self.parameters:
            self.parameters['R'] = diag([1.0e-1 for i in range(num_measurements)])
        
        def measure(x):
            x = {key: value for (key, value) in zip(self.__state_keys, x)}
            z = model.output(x)
            return {array(list(z.values()))}

        def state_transition(x, dt):
            x = {key: value for (key, value) in zip(self.__state_keys, x)}
            x = model.next_state(x, self.__input, dt)
            x = model.apply_limits(x)
            return array(list(x.values()))

        self.sigma_points = kalman.MerweScaledSigmaPoints(num_states, alpha=self.parameters['alpha'], beta=self.parameters['beta'], kappa=self.parameters['kappa'])
        self.filter = kalman.UnscentedKalmanFilter(num_states, num_measurements, self.parameters['dt'], measure, state_transition, self.sigma_points)
        self.filter.Q = self.parameters['Q']
        self.filter.R = self.parameters['R']

    def predict(self, state, future_loading_eqn : Callable, **kwargs) -> PredictionResults:
        """
        Perform a single prediction

        Parameters
        ----------
        state (UncertaintData): Distribution of states
        future_loading_eqn : function (t, x={}) -> z
            Function to generate an estimate of loading at future time t
        options (optional, kwargs): configuration options\n
        Any additional configuration values. Note: These parameters can also be specified in the predictor constructor. The following configuration parameters are supported: \n
            * alpha, beta, kappa: UKF Scaling parameters
            * t0: Starting time (s)
            * dt : Step size (s)
            * horizon : Prediction horizon (s)
            * events : List of events to be predicted (subset of model.events, default is all events)

        Returns (PredictionResults)
        -------
        times: [number]
            Times for each simulated point in format times[index]
        inputs: [[dict]]
            Future input (from future_loading_eqn) for each sample and time in times
            where inputs[sample_id][index] corresponds to time times[sample_id][index]
        states: [[dict]]
            Estimated states for each sample and time in times
            where states[sample_id][index] corresponds to time times[sample_id][index]
        outputs: [[dict]]
            Estimated outputs for each sample and time in times
            where outputs[sample_id][index] corresponds to time times[sample_id][index]
        event_states: [[dict]]
            Estimated event state (e.g., SOH), between 1-0 where 0 is event occurance, for each sample and time in times
            where event_states[sample_id][index] corresponds to time times[sample_id][index]
        toe: UncertainData
            Estimated time where a predicted event will occur for each sample. Note: Mean and Covariance Matrix will both 
            be nan if every sigma point doesnt reach threshold within horizon
        """
        params = deepcopy(self.parameters) # copy parameters
        params.update(kwargs) # update for specific run
        events_to_predict = params['events']

        # Optimizations 
        dt = params['dt']
        model = self.model
        filt = self.filter
        sigma_points = self.sigma_points
        n_points = sigma_points.num_sigmas()
        threshold_met = model.threshold_met

        # Update State 
        self.__state_keys = state_keys = state.mean.keys()  # Used to maintain ordering as we strip keys and return
        filt.x = [x for x in state.mean.values()]
        filt.P = state.cov

        # Setup first states
        t = params['t0']
        save_pt_index = 0
        ToE = {key: [float('nan') for i in range(n_points)] for key in events_to_predict}  # Keep track of final ToE values
        last_state = {key: [float('nan') for i in range(n_points)] for key in events_to_predict}  # Keep track of final state values

        times = []
        inputs = []
        states = []
        save_freq = params['save_freq']
        next_save = t + save_freq
        save_pts = params['save_pts']
        save_pts.append(1e99)  # Add last endpoint
        def update_all():
            times.append(t)
            inputs.append(deepcopy(self.__input))  # Avoid optimization where u is not copied
            x_dict = MultivariateNormalDist(self.__state_keys, filt.x, filt.P)
            states.append(x_dict)  # Avoid optimization where x is not copied

        # Optimization
        state_keys = self.__state_keys

        # Simulation
        update_all()  # First State
        while t < params['horizon']:
            # Iterate through time
            t += dt
            mean_state = {key: x for (key, x) in zip(state_keys, filt.x)}
            self.__input = future_loading_eqn(t, mean_state)
            filt.predict(dt=dt)

            # Record States
            if (t >= next_save):
                next_save += save_freq
                update_all()
            if (t >= save_pts[save_pt_index]):
                save_pt_index += 1
                update_all()
            
            # Check that any sigma point has hit event
            points = sigma_points.sigma_points(filt.x, filt.P)
            all_failed = True
            for i, point in zip(range(n_points), points):
                x = {key: x for (key, x) in zip(state_keys, point)}
                t_met = threshold_met(x)

                # Check Thresholds
                for key in events_to_predict:
                    if t_met[key]:
                        if isnan(ToE[key][i]):
                            # First time event has been reached
                            ToE[key][i] = t
                            last_state[key][i] = deepcopy(x)
                    else:
                        all_failed = False  # This event for this sigma point hasn't been met yet
            if all_failed:
                # If all events have been reched for every sigma point
                break 
        
        # Prepare Results
        pts = array([[e for e in ToE[key]] for key in ToE.keys()])
        pts = transpose(pts)
        mean, cov = kalman.unscented_transform(pts, sigma_points.Wm, sigma_points.Wc)

        # Transform final state into {event_name: MultivariateNormalDist}
        final_state = {}
        for event_key in last_state.keys():
            last_state_pts = array([[last_state_i[state_key] for state_key in state_keys] for last_state_i in last_state[event_key]])
            # last_state_pts = transpose(last_state_pts)
            last_state_mean, last_state_cov = kalman.unscented_transform(last_state_pts, sigma_points.Wm, sigma_points.Wc)
            final_state[event_key] = MultivariateNormalDist(state_keys, last_state_mean, last_state_cov)

        # At this point only time of event, inputs, and state are calculated 
        inputs_prediction = UnweightedSamplesPrediction(times, [inputs])
        state_prediction = Prediction(times, states)
        output_prediction = LazyUTPrediction(state_prediction, sigma_points, kalman.unscented_transform, model.output)
        event_state_prediction = LazyUTPrediction(state_prediction, sigma_points, kalman.unscented_transform, model.event_state)
        time_of_event = MultivariateNormalDist(ToE.keys(), mean, cov)
        time_of_event.final_state = final_state
        return PredictionResults(
            times, 
            inputs_prediction, 
            state_prediction, 
            output_prediction, 
            event_state_prediction, 
            time_of_event
        )  
      
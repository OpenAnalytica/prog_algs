# Copyright © 2021 United States Government as represented by the Administrator of the National Aeronautics and Space Administration.  All Rights Reserved.

from copy import deepcopy
from typing import Callable
import numpy as np
from warnings import warn
from filterpy import kalman
from prog_models import LinearModel
from . import state_estimator
from ..uncertain_data import MultivariateNormalDist, UncertainData

class KalmanFilter(state_estimator.StateEstimator):
    """
    An Kalman Filter (KF) for state estimation

    This class defines logic for performing a kalman filter with a LinearModel (see Prognostics Model Package). This filter uses measurement data with noise to generate a state estimate and covariance matrix. 

    The supported configuration parameters (keyword arguments) for UKF construction are described below:

    Constructor Configuration Parameters:
        alpha: float
            KF Scaling parameter. An alpha > 1 turns this into a fading memory filter.
        t0 : float
            Starting time (s)
        dt : float 
            time step (s)
        Q : List[List[float]]
            Process Noise Matrix 
        R : List[List[float]]
            Measurement Noise Matrix 

    Note:
        The Kalman Filter does not support a custom measurement function
    """
    default_parameters = {
        'alpha': 1, 
        't0': -1e-10,
        'dt': 1
    } 
    
    def __init__(self, model, x0, measurement_eqn : Callable = None, **kwargs):
        # Note: Measurement equation kept in constructor to keep it consistent with other state estimators. This way measurement equation can be provided as an ordered argument, and will just be ignored here
        if not isinstance(model, LinearModel):
            raise Exception('Kalman Filter only supports Linear Models (i.e., models derived from prog_models.LinearModel)')

        super().__init__(model, x0, None, **kwargs)

        self.x0 = x0

        if 'Q' not in self.parameters:
            self.parameters['Q'] = np.diag([1.0e-3 for i in x0.keys()])
        if 'R' not in self.parameters:
            # Size of what's being measured (not output) 
            # This is determined by running the measure function on the first state
            self.parameters['R'] = np.diag([1.0e-3 for i in range(model.n_outputs)])
        
        num_states = len(x0.keys())
        num_inputs = model.n_inputs + 1
        num_measurements = model.n_outputs
        F = deepcopy(model.A)
        B = deepcopy(model.B)
        if np.size(B) == 0:
            # If B is empty, replace with E. 
            # Append wont work if B is empty
            B = deepcopy(model.E)
        else:
            B = np.append(B, deepcopy(model.E), 0)

        self.filter = kalman.KalmanFilter(num_states, num_measurements, num_inputs)

        self.__state_keys = list(x0.keys())
        if isinstance(x0, dict) or isinstance(x0, model.StateContainer):
            warn("Warning: Use UncertainData type if estimating filtering with uncertain data.")
            self.filter.x = np.array([[x0[key]] for key in model.states]) # x0.keys()
            self.filter.P = self.parameters['Q'] / 10
        elif isinstance(x0, UncertainData):
            x_mean = x0.mean
            self.filter.x = np.array([[x_mean[key]] for key in model.states])

            # Reorder covariance to be in same order as model.states
            mapping = {i: list(x0.keys()).index(key) for i, key in enumerate(model.states)}
            cov = x0.cov  # Set covariance in case it has been calculated
            mapped_cov = [[cov[mapping[i]][mapping[j]] for j in range(len(cov))] for i in range(len(cov))] # Set covariance based on mapping
            self.filter.P = np.array(mapped_cov)
        else:
            raise TypeError("TypeError: x0 initial state must be of type {{dict, UncertainData}}")

        self.filter.Q = self.parameters['Q']
        self.filter.R = self.parameters['R']
        self.filter.F = F
        self.filter.B = B

    def estimate(self, t : float, u, z):
        """
        Perform one state estimation step (i.e., update the state estimate)

        Parameters
        ----------
        t : double
            Current timestamp in seconds (≥ 0.0)
            e.g., t = 3.4
        u : dict
            Measured inputs, with keys defined by model.inputs.
            e.g., u = {'i':3.2} given inputs = ['i']
        z : dict
            Measured outputs, with keys defined by model.outputs.
            e.g., z = {'t':12.4, 'v':3.3} given inputs = ['t', 'v']
        """
        assert t > self.t, "New time must be greater than previous"

        dt = t - self.t
        # Create u array, ensuring order of model.inputs
        inputs = np.array([u[key] for key in self.model.inputs])

        # Add row of ones (to account for constant E term)
        if np.size(inputs) == 0:
            inputs = np.array([[1]])
        else:
            inputs = np.append(inputs, [[1]], 0)

        self.t = t

        # Update equations
        # prog_models is dx = Ax + Bu + E
        # kalman_models is x' = Fx + Bu, where x' is the next state
        # Therefore we need to add the diagnol matrix 1 to A to convert
        # And A and B should be multiplied by the time step
        B = np.multiply(self.filter.B, dt) 
        F = np.multiply(self.filter.F, dt) + np.diag([1]* self.model.n_states)

        # Predict
        self.filter.predict(u = inputs, B = B, F = F)

        # Create z array, ensuring order of model.outputs
        outputs = np.array([z[key] for key in self.model.outputs])

        # Subtract D from outputs
        # This is done because prog_models expects the form: 
        #   z = Cx + D
        # While kalman expects
        #   z = Cx
        outputs = outputs - self.model.D

        self.filter.update(outputs, H=self.model.C)
    
    @property
    def x(self) -> MultivariateNormalDist:
        """
        Getter for property 'x', the current estimated state. 

        Example
        -------
        state = observer.x
        """
        return MultivariateNormalDist(self.model.states, self.filter.x.ravel(), self.filter.P)

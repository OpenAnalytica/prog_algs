# Copyright © 2021 United States Government as represented by the Administrator of the National Aeronautics and Space Administration. All Rights Reserved.

from prog_models.models.thrown_object import ThrownObject
from prog_algs import *
from prog_algs.uncertain_data import UnweightedSamples

"""
In this example we are using the UTPredictor to predict a specific event, in this case impact. This will then ignore the other events which are not of interest.
"""

def run_example():
    ## Setup
    def future_loading(t, x = None):
        return {}

    m = ThrownObject()
    initial_state = m.initialize({}, {})

    ## State Estimation - perform a single ukf state estimate step
    filt = state_estimators.UnscentedKalmanFilter(m, initial_state)
    filt.estimate(0.1, {}, m.output(initial_state))

    ## Prediction - Predict EOD given current state
    # Setup prediction
    pred = predictors.UnscentedTransformPredictor(m)

    # Predict with a step size of 0.1
    mc_results = pred.predict(filt.x, future_loading, dt=0.1, save_freq= 1, events=['impact'])

    # Print Results
    for i, time in enumerate(mc_results.times):
        print('\nt = {}'.format(time))
        print('\tu = {}'.format(mc_results.inputs.snapshot(i).mean))
        print('\tx = {}'.format(mc_results.states.snapshot(i).mean))
        print('\tz = {}'.format(mc_results.outputs.snapshot(i).mean))
        print('\tevent state = {}'.format(mc_results.states.snapshot(i).mean))

    # Note only impact event is shown here
    print('\nToE:', mc_results.time_of_event.mean)

# This allows the module to be executed directly 
if __name__ == '__main__':
    run_example()

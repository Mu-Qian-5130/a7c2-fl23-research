"""Upstream direct-target numerical fitter; R5 export/server layers omitted."""
import numpy as np
import pc_stages
from residual_grid import evaluate,pack,unpack,response_matrix

def fit_target(base, target, weights, response, progress=None, parameter_smoothing=0,
               continuity=None, target_neighborhood=None, hue_direction=None,
               training_penalties=True, polish_rounds=0):
    """Fit the exported single grid to actual targets, using training rows only.

    No PC teacher or synthetic teacher targets contribute to this objective.
    Candidate selection uses the same training loss and smoothness policy as
    historical compression; holdout metrics are computed only afterwards.
    """
    if type(training_penalties) is not bool:
        raise ValueError('training_penalties must be a boolean')
    if not training_penalties:
        parameter_smoothing, continuity, target_neighborhood, hue_direction = 0, None, None, None
    from optimizer_policy import display_cost_rows, refine_grid
    from parameter_smoothing import multiplier, grid_cost
    base, target, weights = [np.asarray(v, dtype=float) for v in (base, target, weights)]
    if (base.ndim != 2 or base.shape[1] != 3 or target.shape != base.shape
            or len(base) < 2 or weights.shape != (len(base),)
            or not all(np.isfinite(v).all() for v in (base, target, weights))
            or np.any(weights <= 0)):
        raise ValueError('Expected matching finite training RGB targets and positive weights')
    response = response_matrix(response)
    mass = weights / weights.sum()
    candidates = []
    strengths = (0.,) if not training_penalties or target_neighborhood is not None or hue_direction is not None else np.array((.0001, .001, .01))*multiplier(parameter_smoothing)
    for index, strength in enumerate(strengths, 1):
        if progress: progress(stage='富士目标直接拟合网格', round=index, total_rounds=len(strengths), state='running', sweep=None, point=None)
        grid, solver = pc_stages.fit_response_grid(base, target, mass, response, strength=strength)
        grid, refinement = refine_grid(grid, base, target, np.ones(len(base)), mass,
            sweeps=1, perceptual_weight=.35, response=response,
            progress=(lambda **v: progress(stage='目标网格整数量化微调', **v)) if progress else None,
            parameter_smoothing=parameter_smoothing)
        continuity_audit=None
        if continuity is not None or target_neighborhood is not None or hue_direction is not None:
            from continuity_grid import constrain
            grid,continuity_audit=constrain(grid,base,target,weights,response,parameter_smoothing,
                continuity,progress,target_neighborhood=target_neighborhood,hue_direction=hue_direction)
        # Score exactly the signed-7-bit coefficients that will be exported.
        grid = unpack(pack(grid))
        prediction = evaluate(base, grid, response)
        score = float(display_cost_rows(prediction, target, .35)@mass)+grid_cost(grid, parameter_smoothing,response=response)
        if continuity is not None:
            from continuity_grid import penalty
            score+=penalty(grid,response,continuity)
        if target_neighborhood is not None:
            from continuity_grid import neighborhood_penalty
            score+=neighborhood_penalty(grid,response,target_neighborhood)
        if hue_direction is not None:
            from continuity_grid import hue_direction_penalty
            score+=hue_direction_penalty(grid,response,hue_direction)
        candidates.append((score, grid, dict(smoothness=float(strength), score=score,
            solver=solver, quantization_refinement=refinement,output_continuity=continuity_audit)))
    best = min(candidates, key=lambda value: value[0])
    grid = best[1]
    return grid, dict(objective='fuji-target', training_inputs=len(base), synthetic_probes=0,
        train_probe_mass=[1.0, 0.0], selected_smoothness=best[2]['smoothness'],
        candidates=[value[2] for value in candidates], training_only=True,
        parameter_smoothing=parameter_smoothing, teacher=None, training_shape_penalties=bool(training_penalties),
        selection=('training RGB/perceptual data loss only; no shape penalty or holdout fitting' if not training_penalties else
                   'training target loss plus target-neighborhood antiringing; no validation or test fitting'
                   if target_neighborhood is not None else 'training target loss plus actual-response path slope/curvature; no validation or test fitting'),
        limit_fraction=float(np.mean((grid == -64) | (grid == 63))))

"""Numerical gradients and bounded improvement; no private fixtures or USB."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from looktool import nativefit
from looktool.nativefit import Problem, solve


class LinearField:
    def __init__(self, matrix):self.matrix=np.asarray(matrix)
    def __call__(self, rgb):return np.asarray(rgb)@self.matrix
    def derivative(self, rgb):return np.broadcast_to(self.matrix,(len(rgb),3,3)).copy()


class Model:
    def __init__(self):
        self.base=type('Base',(),{})()
        self.base.coordinates=lambda rgb:np.asarray(rgb)
        self.base.forward=LinearField(np.array([[.9,.05,.02],[.04,.92,.04],[.02,.03,.9]]))
        self.base.scale=np.array([.01,.012,.008])
        rng=np.random.default_rng(123)
        self.models=[]
        for _ in range(17):
            matrix=rng.normal(0,.015,(3,3))
            self.models.append((LinearField(-matrix),LinearField(matrix)))
    def bases(self, rgb):
        return np.stack([pair[1](rgb) for pair in self.models],axis=1),np.zeros((len(rgb),17,3))


class NativeFitTests(unittest.TestCase):
    def test_table_refinement_keeps_better_seed_and_retains_seed_diagnostics(self):
        source=np.random.default_rng(3).uniform(.2,.7,(18,3))
        problem=Problem(Model(),source,source,1e-9)
        seed=np.zeros((405,3));diagnostics={'seed_optimizer':{'status':0,'converged':False}}
        result=SimpleNamespace(x=np.full(1215,63.),success=False,nfev=1)
        with patch.object(nativefit.coupledfit,'solve',return_value=(seed,diagnostics)),\
                patch.object(nativefit,'least_squares',return_value=result):
            vector,report=nativefit.table_seed(problem,max_evaluations=1,return_report=True)
        np.testing.assert_array_equal(vector,np.zeros(1232))
        self.assertFalse(report['retained_refinement'])
        self.assertEqual(report['seed'],diagnostics)

    def test_full_analytic_chain_matches_finite_difference(self):
        source=np.random.default_rng(3).uniform(.2,.7,(18,3))
        problem=Problem(Model(),source,source,1e-9)
        vector=np.random.default_rng(4).uniform(-.1,.1,1232)
        jac=problem.jacobian(vector)
        active=np.argsort(np.asarray(abs(jac[:54,:1215]).sum(0)).ravel())[-5:]
        for column in list(active)+[1215,1218,1223,1231]:
            step=np.zeros(1232);step[column]=1e-5
            numeric=(problem.residual(vector+step)-problem.residual(vector-step))/2e-5
            np.testing.assert_allclose(numeric,jac[:,column].toarray().ravel(),atol=2e-8,rtol=1e-5)

    def test_solver_improves_feasible_seed_and_integer_field_stays_bounded(self):
        source=np.random.default_rng(8).uniform(.2,.7,(35,3))
        target=source+np.array([.03,-.02,.01])
        problem=Problem(Model(),source,target,1e-8)
        vector,report=solve(problem,np.zeros(1232),max_evaluations=12)
        self.assertLess(report['objective_after'],report['objective_before']*.1)
        self.assertTrue(np.all(abs(vector[1215:])<=.5))
        self.assertTrue(np.all((vector[:1215]>=-64)&(vector[:1215]<=63)))
        self.assertLess(float(np.abs(problem.prediction(vector)-target).mean()),.01)

    def test_robust_pass_reports_and_improves_its_actual_objective(self):
        source=np.random.default_rng(9).uniform(.2,.7,(30,3))
        target=source+np.array([.025,-.015,.01])
        problem=Problem(Model(),source,target,1e-8)
        vector,report=solve(problem,np.zeros(1232),max_evaluations=12,loss='soft_l1')
        self.assertEqual(report['objective_kind'],'soft_l1')
        self.assertLess(report['objective_after'],report['objective_before']*.2)


if __name__=='__main__':unittest.main()

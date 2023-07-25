"""Phonon properties."""
from __future__ import annotations

import collections
import contextlib
import io
import pickle
from typing import TYPE_CHECKING

from ase.constraints import ExpCellFilter
from ase.optimize.bfgs import BFGS
from ase.optimize.bfgslinesearch import BFGSLineSearch
from ase.optimize.fire import FIRE
from ase.optimize.lbfgs import LBFGS, LBFGSLineSearch
from ase.optimize.mdmin import MDMin
from ase.optimize.sciopt import SciPyFminBFGS, SciPyFminCG
from pymatgen.io.ase import AseAtomsAdaptor

if TYPE_CHECKING:
    import numpy as np
    from ase.optimize.optimize import Optimizer

from .base import PropCalc

OPTIMIZERS = {
    "FIRE": FIRE,
    "BFGS": BFGS,
    "LBFGS": LBFGS,
    "LBFGSLineSearch": LBFGSLineSearch,
    "MDMin": MDMin,
    "SciPyFminCG": SciPyFminCG,
    "SciPyFminBFGS": SciPyFminBFGS,
    "BFGSLineSearch": BFGSLineSearch,
}
if TYPE_CHECKING:
    from ase import Atoms
    from ase.calculators.calculator import Calculator


class TrajectoryObserver(collections.abc.Sequence):
    """Trajectory observer is a hook in the relaxation process that saves the
    intermediate structures.
    """

    def __init__(self, atoms: Atoms) -> None:
        """
        Init the Trajectory Observer from a Atoms.

        Args:
            atoms (Atoms): Structure to observe.
        """
        self.atoms = atoms
        self.energies: list[float] = []
        self.forces: list[np.ndarray] = []
        self.stresses: list[np.ndarray] = []
        self.atom_positions: list[np.ndarray] = []
        self.cells: list[np.ndarray] = []

    def __call__(self) -> None:
        """The logic for saving the properties of an Atoms during the relaxation."""
        self.energies.append(float(self.atoms.get_potential_energy()))
        self.forces.append(self.atoms.get_forces())
        self.stresses.append(self.atoms.get_stress())
        self.atom_positions.append(self.atoms.get_positions())
        self.cells.append(self.atoms.get_cell()[:])

    def __getitem__(self, item):
        return self.energies[item], self.forces[item], self.stresses[item], self.cells[item], self.atom_positions[item]

    def __len__(self):
        return len(self.energies)

    def save(self, filename: str) -> None:
        """Save the trajectory to file.

        Args:
            filename (str): filename to save the trajectory.
        """
        out = {
            "energy": self.energies,
            "forces": self.forces,
            "stresses": self.stresses,
            "atom_positions": self.atom_positions,
            "cell": self.cells,
            "atomic_number": self.atoms.get_atomic_numbers(),
        }
        with open(filename, "wb") as file:
            pickle.dump(out, file)


class RelaxCalc(PropCalc):
    """Calculator for phonon properties."""

    def __init__(
        self,
        calculator: Calculator,
        optimizer: Optimizer | str = "FIRE",
        fmax: float = 0.1,
        steps: int = 500,
        traj_file: str | None = None,
        interval=1,
    ):
        """
        Args:
            calculator: ASE Calculator to use.
            optimizer (str or ase Optimizer): the optimization algorithm.
                Defaults to "FIRE"
            fmax (float): total force tolerance for relaxation convergence. fmax is a sum of force and stress forces.
            steps (int): max number of steps for relaxation.
            traj_file (str): the trajectory file for saving
            interval (int): the step interval for saving the trajectories.
        """
        self.calculator = calculator
        if isinstance(optimizer, str):
            optimizer_obj = OPTIMIZERS.get(optimizer, None)
        elif optimizer is None:
            raise ValueError("Optimizer cannot be None")
        else:
            optimizer_obj = optimizer

        self.opt_class: Optimizer = optimizer_obj
        self.fmax = fmax
        self.interval = interval
        self.steps = steps
        self.traj_file = traj_file

    def calc(self, structure) -> dict:
        """
        All PropCalc should implement a calc method that takes in a pymatgen structure and returns a dict. Note that
        the method can return more than one property.

        Args:
            structure: Pymatgen structure.

        Returns: {"prop name": value}
        """
        ase_adaptor = AseAtomsAdaptor()
        atoms = ase_adaptor.get_atoms(structure)
        atoms.set_calculator(self.calculator)
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            obs = TrajectoryObserver(atoms)
            atoms = ExpCellFilter(atoms)
            optimizer = self.opt_class(atoms)
            optimizer.attach(obs, interval=self.interval)
            optimizer.run(fmax=self.fmax, steps=self.steps)
            obs()
        if self.traj_file is not None:
            obs.save(self.traj_file)
        atoms = atoms.atoms

        final_structure = ase_adaptor.get_structure(atoms)
        lattice = final_structure.lattice

        return {
            "final_structure": final_structure,
            "a": lattice.a,
            "b": lattice.b,
            "c": lattice.c,
            "alpha": lattice.alpha,
            "beta": lattice.beta,
            "gamma": lattice.gamma,
            "volume": lattice.volume,
        }
# Abaqus2Py

[![GitHub license](https://img.shields.io/badge/license-BSD-blue)](https://github.com/bessagroup/abaqus2py)
[![DOI](https://zenodo.org/badge/772585162.svg)](https://doi.org/10.5281/zenodo.20591698)

[**Docs**](https://abaqus2py.readthedocs.io)
| [**GitHub**](https://github.com/bessagroup/abaqus2py)
| [**PyPI**](https://pypi.org/project/abaqus2py/)
| [**Zenodo**](https://zenodo.org/record/20591698)

**First publication:** March 15, 2024

***

## Summary

**Abaqus2Py** is a thin Python interface for driving ABAQUS finite-element
simulations from regular Python function calls. It wraps the lifecycle of a
simulation—preprocessing, job submission, and postprocessing—behind a small
API, so that running an ABAQUS model becomes as simple as calling a function
and reading back its results.

## Statement of need

ABAQUS is a widely used finite-element solver, but it is driven through its own
command-line tools and Python-2 scripting interpreter, which makes it awkward
to embed in modern, data-driven workflows. Generating large datasets of
simulations—for surrogate modeling, design optimization, or machine
learning—requires gluing together input-file generation, job submission,
result extraction, and synchronization with the solver, all while bridging the
gap to a contemporary Python 3 environment.

Abaqus2Py provides that glue. It generates the preprocess/postprocess scripts
that ABAQUS executes in its own interpreter, submits jobs through the `abaqus`
CLI, polls for completion, and reads the results back into Python 3—handling
the Python-2 pickle compatibility details transparently. ABAQUS itself is
**not** a Python dependency, so the library can be developed and tested without
it installed. Through its `f3dasm` adapter, Abaqus2Py plugs directly into
data-driven design pipelines, turning an `ExperimentData` of design parameters
into a batch of ABAQUS simulations with reproducible, HPC-ready orchestration.

## Key Features

- **Two public classes** — `AbaqusSimulator` (standalone driver) and
  `F3DASMAbaqusSimulator` (an `f3dasm.DataGenerator` adapter).
- **Full simulation lifecycle** — `preprocess` → `submit` → `postprocess`,
  or a single combined `run`.
- **ABAQUS-free development** — ABAQUS is invoked via the `abaqus` CLI, never
  imported, so the package installs and tests without a solver present.
- **Python-2 ↔ Python-3 bridging** — generated scripts and pickle (de)coding
  transparently handle ABAQUS's Python-2 interpreter.
- **f3dasm integration** — run simulations over an `ExperimentData` with
  per-sample working directories and HPC/SLURM orchestration.

## Dependencies

Abaqus2Py builds on the following packages:

| Package | Description |
| --- | --- |
| [f3dasm](https://github.com/bessagroup/f3dasm) | Framework for data-driven design and analysis of structures and materials |
| [ABAQUS](https://www.3ds.com/products/simulia/abaqus) | Finite-element solver, driven through its `abaqus` CLI (not a Python dependency) |

## Authorship

**Authors**:
- Jiaxiang Yi ([J.Yi@tudelft.nl](mailto:J.Yi@tudelft.nl))
- Martin van der Schelling ([M.P.vanderSchelling@tudelft.nl](mailto:M.P.vanderSchelling@tudelft.nl))

**Authors affiliation:**
- Bessa Research Group @ Delft University of Technology

**Maintainers:**
- Martin van der Schelling ([M.P.vanderSchelling@tudelft.nl](mailto:M.P.vanderSchelling@tudelft.nl))

**Maintainers affiliation:**
- Bessa Research Group @ Delft University of Technology

## Getting started

### Installation instructions for users

The package is available on PyPI:

```bash
pip install abaqus2py
```

Alternatively, install the latest version from source:

```bash
git clone https://github.com/bessagroup/abaqus2py.git
cd abaqus2py
pip install -e .
```

> Abaqus2Py drives the solver through the `abaqus` command-line tool; a working
> ABAQUS installation is required at runtime, but not to install or test the
> package.

### Installation instructions for developers

To install the package for development (or for building the mkdocs
documentation), install the optional dependency groups after cloning:

```bash
pip install -e '.[dev,docs,tests]'
```

This project is `uv`-managed, so you can equivalently run `uv sync`. See the
[Contributing Guide](CONTRIBUTING.md) for detailed development instructions, and
the [Getting Started Guide](docs/usage.ipynb) for a walkthrough of the API.

## Studies

`studies/fragile_becomes_supercompressible/` is a full worked example
reproducing Bessa et al. (2019), wiring `F3DASMAbaqusSimulator` into a
Hydra-configured, HPC-oriented two-stage (linear-buckle → Riks) f3dasm
workflow. The accompanying ABAQUS modeling scripts live in `scripts/`. See
`studies/fragile_becomes_supercompressible/main.py` for the canonical
end-to-end usage pattern.

## Community Support

* If you find any **issues, bugs or problems** within this repository, please use the [GitHub issue tracker](https://github.com/bessagroup/abaqus2py/issues) to report them.
* If you have **questions, feature requests or ideas** for this project, please use the [GitHub Discussions](https://github.com/bessagroup/abaqus2py/discussions)

Please refer to abaqus2py's [Code of Conduct](CODE_OF_CONDUCT.md)

## Citing

If you use Abaqus2Py in your research, please cite it. Citation metadata is
provided in [CITATION.cff](CITATION.cff); the corresponding BibTeX entry is:

```bibtex
@software{abaqus2py,
  author  = {Yi, Jiaxiang and van der Schelling, Martin P.},
  title   = {{Abaqus2Py: A Python interface for running ABAQUS simulations}},
  year    = {2026},
  version = {1.1.0},
  url     = {https://github.com/bessagroup/abaqus2py}
}
```

## License

Copyright 2026, Bessa Research Group

All rights reserved.

This project is licensed under the BSD 3-Clause License. See [LICENSE](LICENSE) for the full license text.
</content>
</invoke>

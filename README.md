# snc2fst

## Installation

```bash
conda install mazadegan::snc2fst
```

## Developer Notes

### Setup

```bash
pip install -e .
```

### Releasing a new version

1. Bump the version in `pyproject.toml` and `conda-recipe/meta.yaml`.

2. Build the conda package:

```bash
conda build conda-recipe
# or
conda-build conda-recipe
```

3. Upload to anaconda channel:

```bash
anaconda login
anaconda upload ~/miniforge3/envs/snc2fst/conda-bld/noarch/snc2fst-<version>-*.conda
```

## License

Apache 2.0. See [LICENSE](LICENSE).

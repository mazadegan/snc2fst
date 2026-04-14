# snc2fst

## Installation

```bash
conda install -c conda-forge mazadegan::snc2fst
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
conda-build conda-recipe -c mazadegan -c conda-forge -c defaults
```

3. Test the local build before uploading:

```bash
conda install ~/miniforge3/envs/snc2fst/conda-bld/noarch/snc2fst-<version>-*.conda
```

4. Upload to anaconda channel:

```bash
anaconda login
anaconda upload ~/miniforge3/envs/snc2fst/conda-bld/noarch/snc2fst-<version>-*.conda
```

## License

Apache 2.0. See [LICENSE](LICENSE).

# Type Stubs for trueskill

This directory contains type stubs for the `trueskill` library, providing comprehensive type annotations for better IDE support and static type checking with basedpyright.

## Usage

To use these type stubs, add the `stubs` directory to your Python path:

```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)/stubs"
```

Or when running basedpyright:

```bash
PYTHONPATH=stubs uv run basedpyright your_file.py
```

## What's Included

The type stubs provide type annotations for:

- **Rating class**: The core rating object with properties like `mu`, `sigma`, `pi`, `tau`, and `exposure`
- **TrueSkill class**: The environment configuration class
- **rate_1vs1()**: Function for rating 1v1 matches
- **rate()**: Function for rating multi-player matches  
- **setup()**: Function for configuring the global TrueSkill environment
- **quality_1vs1()**: Function for calculating match quality
- **quality()**: Function for calculating multi-player match quality
- **win_probability()**: Function for calculating win probabilities
- **draw_probability()**: Function for calculating draw probabilities
- **global_env()**: Function for getting the global environment
- **set_global_env()**: Function for setting the global environment

## Features

- Complete type annotations for all public APIs
- Support for both basic and advanced usage patterns
- Proper handling of optional parameters and return types
- Full support for the Rating class properties and methods
- Type-safe function signatures for all rating operations

## Testing

The stubs have been tested with:
- Basic functionality verification
- basedpyright type checking
- Integration with the existing codebase

## Files

- `trueskill/__init__.pyi`: Main type stub file with all type annotations
- `trueskill/py.typed`: Marker file indicating this package provides type information

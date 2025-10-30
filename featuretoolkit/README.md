# featuretoolkit v0.4.2

simple utilities for cleaning, harmonizing, and region-blocking landslide event data. 
designed around two common sources:
- **COOLR** (NASA Cooperative Open Online Landslide Repository)
- **GFLD** (Global Fatal Landslide Database)

the package keeps dataset-specific functions separate and puts shared tools in a common module, and also includes data transformation capabilities for both pre-processing (before training) and pre-inference data normalization.
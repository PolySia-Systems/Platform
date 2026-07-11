# Optional Rendered Assets

Canonical diagrams are the Mermaid files in `../sources/`. This directory may
contain SVG exports when a compatible renderer is already available. SVG files
must be regenerated from the matching source, reviewed visually, and committed
with the source change.

No PNG export is required for this pack. Do not add a Mermaid renderer to the
PolySia Python runtime or project dependencies.

# 3D model sources

This directory has the SolidCraft sources of the 3D models that the M17 Project draws.
The footprints in `footprints/` embed the STEP export of each model.
The STEP files are not in this directory. Export them from the sources.

Draw a model when the manufacturer and the KiCad library do not supply a model
that we may publish. Use the dimensions in the manufacturer drawing.
Do not copy models from SamacSys, SnapEDA, Ultra Librarian, EasyEDA or similar
sites. You can measure such a model for reference only.

Give the source the name of the footprint, for example
`SMA_AdamTech_RF2-04A-T-00-50-G_Vertical.sc`.

## Change a model

1. Open the `.sc` file in SolidCraft and change the design.
2. Name the bodies and set the colors (for example gold plating, PTFE white, plastic black).
3. Export the STEP file to a temporary directory. Use the name of the footprint, for example
   `SMA_AdamTech_RF2-04A-T-00-50-G_Vertical.step`.
4. Embed the STEP file in the footprint again. In KiCad: Footprint Editor,
   Footprint Properties, 3D Models, add the file and select "Embed".
5. Keep the entry in `footprints/models.yaml` up to date.

The models in this directory are under the MIT license of this repository.

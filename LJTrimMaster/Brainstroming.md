To not be included in plan. Only a draft

## Unity Intergration

Idea 1:
Unity side code will scan all materials that uses TrimMaster image slot.

List is generated for trim master to read.

Create linked textures for unity. Material image reference a trim sheet instance.
TrimMaster -> Unity Material

Settings will contain trimsheet resolution.

Idea 2:
Unity side code have a list to mark material for tool use. There will be be generated image placeholder holder slots provided by the tool. the user must place a image placeholder slot inside the material so the tool can know what trim goes to what image slot.

In the tool inside a single trim sheet tab there will be a panel to add supported unity materials and what slot to replace with what trim sheet.

Settings will contain trimsheet resolution.

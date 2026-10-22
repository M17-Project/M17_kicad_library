# M17 KiCad library

This is the shared KiCad 10 library for the hardware of the M17 Project.
Each board repository uses this library as a git submodule.

## Idea

Each part in this library is an "atomic" part. An atomic part is one symbol for
one orderable component. The symbol has all the data for that component:

- value and footprint,
- manufacturer and manufacturer part number (MPN),
- Mouser number (always) and LCSC number (if JLCPCB has the part),
- the URL of the official datasheet.

When you place an atomic part in a schematic, the BOM for that part is complete.
You do not search for order numbers later.

Mouser is the primary source for all parts. Each part on a BOM must have a Mouser
number, so that a person can order all parts at Mouser. If Mouser does not sell a
part, the part must have a `source`: a URL or a short note that tells where to buy
it, for example `LCSC only`. The LCSC number is recommended for people who order
assembly at JLCPCB.

Each board repository uses the library at a fixed commit (git submodule). Thus a
board revision always builds with the same library. A board updates the library
only when its maintainer decides to do it.

## How it works

```
parts/*.yaml ─┐
              ├─> m17lib generate ─> symbols/M17_*.kicad_sym ─> board projects
base-symbols/ ┘                      (atomic parts)
footprints/  ───────────────────────────────────────────────> board projects
```

1. `parts/*.yaml` has the data for each part. One YAML file makes one KiCad
   symbol library. For example `parts/passives.yaml` makes `symbols/M17_Passives.kicad_sym`.
2. `base-symbols/` has the symbol drawings. Many parts use the same drawing,
   for example all resistors use `Device:R`.
3. `m17lib generate` makes the files in `symbols/`. Each atomic part is a KiCad
   derived symbol (`extends`) of its base symbol, with all the fields set.
   A copy of each base symbol is in the same file with the name `BASE_<name>`.
   Do not place `BASE_` symbols.
4. `footprints/` has the footprints that KiCad does not supply. The 3D model is
   embedded in the footprint file. Parts with a standard package use the KiCad
   footprint library. KiCad 10 supplies those footprints and their 3D models.

The files in `symbols/` are generated, but they are in git. Thus a board project
needs only KiCad, and no Python tools. The generator writes the files in the
same format as KiCad, so a save in KiCad does not change them.

### Directories

| Directory | Contents | Edit by hand |
|---|---|---|
| `parts/` | Part data in YAML | Yes |
| `base-symbols/` | Base symbol drawings | Yes, in KiCad |
| `symbols/` | Atomic symbol libraries | No, generated |
| `footprints/` | Footprints with embedded 3D models | Yes, in KiCad |
| `footprints/models.yaml` | Source of each embedded 3D model | Yes |
| `templates/board/` | Template for a new board project | Yes |
| `make/board.mk` | Shared build rules for board projects | Yes |
| `tools/m17board` | Board tool, Python 3 only | Yes |
| `src/m17lib/` | Generator and tools | Yes |

## Make a new board

1. Make a new, empty git repository for the board and clone it.
2. Add this library as a submodule. The path must be `lib`:

   ```sh
   git submodule add https://github.com/M17-Project/M17_kicad_library.git lib
   ```

3. Make the KiCad project:

   ```sh
   python3 lib/tools/m17board new rru2-rf-sx1255 --title "RRU2 RF SX1255" --stackup JLC04081H-7628
   ```

   This makes:

   - the KiCad 10 project, schematic and 4 layer board,
   - the JLCPCB stackup and the JLCPCB design rules,
   - `sym-lib-table` and `fp-lib-table` for the library,
   - a `Makefile`, a GitHub CI workflow, `.gitignore` and `README.md`.

   Stackups (JLCPCB, 4 layers, 1 oz outer and 0.5 oz inner copper, no extra cost):

   | Name | Thickness | Use |
   |---|---|---|
   | `JLC04101H-7628` | 1.0 mm | Default |
   | `JLC04081H-7628` | 0.8 mm | M.2 cards |
   | `JLC04081H-3313` | 0.8 mm | M.2 cards with narrow 50 Ω lines (thin prepreg) |

   Check the stackup on the JLCPCB web site before you order. JLCPCB can change it.

4. Commit all files and push.

To clone a board repository with its library, use `git clone --recursive`.

### Work in progress

A new board starts as a work in progress. The KiCad text variable `WIP_MARK`
in the project marks it. When `WIP_MARK` has a text:

- `make check` shows the layout DRC findings (for example unrouted nets and
  parts outside the board) as warnings. ERC, the schematic parity check and the
  BOM check stay strict. Thus the CI is green while the layout is not finished.
- The ZIP file with the Gerbers and the `fab` directory get the file
  `DO-NOT-ORDER.txt`.
- The schematic shows the text of `${WIP_MARK}` in the top right corner, in KiCad
  and in the PDF: "WORK IN PROGRESS - DO NOT ORDER".

When the design is complete and checked, make `WIP_MARK` empty. Use the command:

```sh
python3 lib/tools/m17board wip off
```

Or in KiCad: File, Schematic Setup, Text Variables. Then `make check` is strict
again and the text disappears. To mark a board again, run
`python3 lib/tools/m17board wip on`.

### Board build

The board `Makefile` includes `lib/make/board.mk`. It has these targets:

| Target | Result |
|---|---|
| `make check` | ERC, DRC with schematic parity, and the BOM check. Any violation is an error. |
| `make` | All checks, then all outputs in `build/` |
| `make lib-update` | Update the library submodule to the latest commit |
| `make docker` | Run `make` in the same Docker image as the CI |

The outputs are the schematic PDF, the BOMs, the position files, the Gerbers,
the STEP model and the renders. There are three BOM files:

- `*_bom_mouser.csv`: the parts from Mouser, for the Mouser BOM tool,
- `*_bom_other.csv`: the parts that Mouser does not sell, with their source,
- `*_bom_jlcpcb.csv`: all parts with LCSC numbers, for JLCPCB assembly.

The BOM check fails if a part has no Mouser number and no source. ERC and DRC also fail if a
symbol or footprint is different from the library. Then update the design from
the library in KiCad (Tools, Update Symbols from Library and Update Footprints from Library).

## Add a part

All new parts and all part changes go through a pull request.

1. Find the part at Mouser. Write down the Mouser number and the MPN. If Mouser
   does not sell the part, write down where to buy it (`source`).
2. Find the official datasheet on the web site of the manufacturer. Use a direct
   URL to the PDF if possible. Do not add the PDF file to this repository.
3. If JLCPCB has the part, write down the LCSC number (`C` and digits).
4. Add the part to the applicable file in `parts/`. See [Part fields](#part-fields).
5. Get the symbol:
   - If KiCad has the symbol, copy it into `base-symbols/`:

     ```sh
     uv run m17lib import-symbol Timer_PLL:ADF4002BCPZ
     ```

   - If KiCad does not have it, draw it in a `base-symbols/M17_Base_*.kicad_sym` file.
     See [Sources that you must not copy](#sources-that-you-must-not-copy).
6. Get the footprint:
   - Use a KiCad footprint if it agrees with the land pattern in the datasheet.
   - If not, add a footprint to `footprints/M17_*.pretty`. Embed the 3D model
     and add the model to `footprints/models.yaml`.
7. Make the libraries and run the tests. If you enabled the git hook (see
   [Generated files](#generated-files)), the commit makes the libraries for you.

   ```sh
   uv run m17lib generate
   uv run pytest
   ```

8. Check your parts and make the previews:

   ```sh
   uv run m17lib check PART_ID --out check
   ```

   Open `check/report.md`. Correct all errors.
9. Open a pull request. Commit the YAML change and the changed files in `symbols/`
   together. The pull request template has a checklist.

### Automatic check of a pull request

For each pull request, the CI finds the parts and footprints that the pull
request adds or changes. Then it does these checks:

| Item | Checks |
|---|---|
| Part data | Mouser number or source, datasheet URL, LCSC number (warning only) |
| Symbol | Pin numbers, pins on the 1.27 mm grid, duplicate pin numbers, pin types |
| Symbol and footprint | Each symbol pin has a pad |
| Footprint | Courtyard, F.Fab outline, pads, solder mask and paste openings, footprint type, 3D model |
| Silkscreen | Text is 0.8 x 0.8 mm and 0.15 mm thick, lines are 0.15 mm or wider |
| Manufacturing | KiCad DRC with the JLCPCB rules: clearances, holes, annular rings, silkscreen on pads |

The CI also makes a picture of the symbol, the footprint and a 3D view of the
footprint on a small board. Then it adds a comment to the pull request with the
result, the pictures and a clear description of each error. The images are kept
in the `part-check-images` branch.

To set the silkscreen text of all footprints to the correct size, run:

```sh
uv run m17lib fix-silk
```

### Sources that you must not copy

This repository is public. Add only data that we may publish under its licenses.

- Draw symbols and footprints from the manufacturer datasheet, or copy them from
  the KiCad library.
- Get 3D models from the manufacturer or from the KiCad 3D model library.
- Do NOT copy symbols, footprints or 3D models from EasyEDA/LCSC (also through
  `easyeda2kicad`), SnapEDA, Ultra Librarian or similar sites. Their terms do not
  allow redistribution. You can use them privately to compare with your drawing.
- Do not copy the Raspberry Pi Compute Module symbols and footprints from the
  Raspberry Pi IO board design files. These files have no license, so we cannot
  publish copies under the MIT license. Draw them from the mechanical drawing
  and the pinout in the Compute Module datasheet.

### Part fields

| YAML key | KiCad field | Required |
|---|---|---|
| `part_id` | Symbol name | Yes |
| `type` | `Type` | Yes |
| `symbol` | Base symbol, `Library:Name` | Yes |
| `footprint` | `Footprint` | Yes, for BOM parts |
| `value` | `Value` | Yes |
| `manufacturer` | `Manufacturer` | Yes |
| `mpn` | `MPN` | Yes |
| `mouser` | `Mouser` | Yes, for BOM parts, if Mouser sells the part |
| `lcsc` | `LCSC` | No, but recommended |
| `source` | `Source`, where to buy the part if Mouser does not sell it | Yes, if `mouser` is empty |
| `datasheet` | `Datasheet`, an `https://` URL | Yes |
| `description` | `Description` | Yes |
| `in_bom` | Set `false` for parts that are not on the BOM, for example a logo | No |

Other keys become KiCad fields with the same name. For example `tolerance` becomes
`Tolerance`. Use only lower case letters, digits and `_` in keys.

The `part_id` is stable. Do not put distributor numbers in the `part_id`.
Examples: `RES-10K-0402`, `CAP-100N-16V-0402-X7R`, `SX1255IWLTRT`.

The only fields for order information are `Mouser`, `LCSC` and `Source`.
Do not add other fields for order numbers.

## Generated files

The files in `symbols/` are generated, but they are in git. A board uses the
library at a fixed commit, so it must get the generated files from that commit.
Then a person who opens a board needs only KiCad.

Each time you change `parts/` or `base-symbols/`, make `symbols/` again and
commit it in the same commit:

```sh
uv run m17lib generate
```

### Git hook

The repository has a git hook that makes `symbols/` for you. The hook is in
`.githooks/pre-commit`. Before each commit, it does these steps:

1. It looks at the files in the commit.
2. If the commit changes `parts/`, `base-symbols/` or the generator in `src/m17lib/`,
   it runs `uv run m17lib generate`.
3. It adds the changed files in `symbols/` to the same commit.
4. If the generator finds an error in the part data, it stops the commit and
   shows the error.

Thus you cannot forget to make `symbols/` again.

Git does not enable hooks from a cloned repository automatically. Enable the
hook once in each clone:

```sh
git config core.hooksPath .githooks
```

To make sure that the hook is enabled, run `git config core.hooksPath`. The
result must be `.githooks`.

To disable the hook, run:

```sh
git config --unset core.hooksPath
```

The hook needs [uv](https://docs.astral.sh/uv/). You do not need the hook. If you
do not use it, run `uv run m17lib generate` yourself before each commit.

The CI does not change your branch. It only checks that `symbols/` is up to date.
If it is not, the check fails and the pull request comment tells you what to do.

## Maintenance

- Do not edit the files in `symbols/`. Edit `parts/` or `base-symbols/`, then run
  `uv run m17lib generate`.
- If you change a base symbol or a footprint, all boards that update the library
  get the change. Make changes that keep the pin numbers and the pad numbers.
- Do not delete a part that a board uses. Set a note in its `description`.
- The CI runs `uv run m17lib generate --check` and `uv run pytest` for each push
  and each pull request.

The tools need [uv](https://docs.astral.sh/uv/) and KiCad 10 (`kicad-cli`).

## Legacy library

The `legacy` branch has the old library for KiCad 7 and KiCad 8. Morgan Diepart
made this library from February 2023 to April 2024 for OpenHT and other M17
designs. OpenHT uses this version through a submodule at a fixed commit.

## License

The MIT license (see `LICENSE`) applies to the tools, the part data, the symbols
and the footprints in this repository, except as follows:

- The symbols in `base-symbols/` that are copies from the KiCad library keep the
  KiCad library license: CC-BY-SA 4.0 with an exception for designs that use them.
  Refer to the [KiCad library license](https://www.kicad.org/libraries/license/).
- The 3D models that are embedded in the footprints are NOT under the MIT license.
  Each model keeps the license or terms of use of its owner. The source of each
  model is in `footprints/models.yaml`. We use only models from the manufacturer
  or from the KiCad 3D model library.

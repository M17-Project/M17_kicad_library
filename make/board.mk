# Shared build rules for M17 board projects.
# A board Makefile sets BOARD and includes this file from the library submodule:
#
#   BOARD := rru2-rf-sx1255
#   include lib/make/board.mk

LIB ?= lib
OUT ?= build
SCH := $(BOARD).kicad_sch
PCB := $(BOARD).kicad_pcb
M17BOARD := python3 $(LIB)/tools/m17board
FAB_HOUSE ?= jlcpcb
RENDER_ARGS ?= --quality high --background transparent -w 1440 -h 1080
DOCKER_IMAGE ?= ghcr.io/slintak/kicad-builder:10.0.7

.PHONY: all check erc drc outputs schematic bom pos step gerbers render lib-update docker clean help
.DEFAULT_GOAL := all

help:
	@echo "make all         Run all checks, then make all outputs in $(OUT)/"
	@echo "make check       ERC, DRC and BOM checks. Any violation is an error"
	@echo "make outputs     Schematic PDF, BOM, positions, STEP, Gerbers, renders"
	@echo "make lib-update  Update the library submodule to the latest version"
	@echo "make docker      Run 'make all' in the pinned KiCad Docker image"

all: check outputs

check: $(OUT)/reports/erc.json $(OUT)/reports/drc.json $(OUT)/bom/$(BOARD)_bom_mouser.csv
	$(M17BOARD) check-reports --erc $(OUT)/reports/erc.json --drc $(OUT)/reports/drc.json

erc: $(OUT)/reports/erc.json
drc: $(OUT)/reports/drc.json

$(OUT)/reports/erc.json: $(SCH) sym-lib-table
	@mkdir -p $(@D)
	kicad-cli sch erc --format json --severity-all --units mm -o $@ $<

$(OUT)/reports/drc.json: $(PCB) $(SCH) fp-lib-table
	@mkdir -p $(@D)
	kicad-cli pcb drc --format json --severity-all --schematic-parity --units mm -o $@ $<

outputs: schematic bom pos step gerbers render

schematic: $(OUT)/$(BOARD)_schematic.pdf
$(OUT)/$(BOARD)_schematic.pdf: $(SCH)
	@mkdir -p $(@D)
	kicad-cli sch export pdf -o $@ $<

# The BOM step also checks that every BOM part has a Mouser number or a Source.
bom: $(OUT)/bom/$(BOARD)_bom_mouser.csv
$(OUT)/bom/$(BOARD)_bom_mouser.csv: $(SCH)
	@mkdir -p $(@D)
	kicad-cli sch export python-bom -o $(OUT)/bom/$(BOARD)_bom.xml $<
	$(M17BOARD) bom $(OUT)/bom/$(BOARD)_bom.xml --mouser $@ --jlcpcb $(OUT)/bom/$(BOARD)_bom_jlcpcb.csv \
		--other $(OUT)/bom/$(BOARD)_bom_other.csv

pos: $(OUT)/fab/$(BOARD)_pos.csv
$(OUT)/fab/$(BOARD)_pos.csv: $(PCB)
	@mkdir -p $(@D)
	kicad-cli pcb export pos --side both --format csv --units mm -o $@ $<
	sed -e '1 s/Ref/Designator/' -e '1 s/PosX/Mid X/' -e '1 s/PosY/Mid Y/' \
		-e '1 s/Rot/Rotation/' -e '1 s/Side/Layer/' $@ > $(OUT)/fab/$(BOARD)_pos_jlcpcb.csv

step: $(OUT)/$(BOARD).step.xz
$(OUT)/$(BOARD).step.xz: $(PCB)
	@mkdir -p $(@D)
	kicad-cli pcb export step --subst-models -o $(OUT)/$(BOARD).step $<
	xz -f $(OUT)/$(BOARD).step

gerbers: $(OUT)/fab/$(BOARD)_gerbers.zip
$(OUT)/fab/$(BOARD)_gerbers.zip: $(PCB)
	@mkdir -p $(@D)
	kikit fab $(FAB_HOUSE) --no-drc $< $(OUT)/fab/kikit
	cp $(OUT)/fab/kikit/gerbers.zip $@

render: $(OUT)/render/$(BOARD)-top.png
$(OUT)/render/$(BOARD)-top.png: $(PCB)
	@mkdir -p $(@D)
	kicad-cli pcb render $(RENDER_ARGS) --side top -o $@ $<
	kicad-cli pcb render $(RENDER_ARGS) --side bottom -o $(OUT)/render/$(BOARD)-bottom.png $<
	kicad-cli pcb render $(RENDER_ARGS) --side top --rotate "315,0,315" -o $(OUT)/render/$(BOARD)-preview.png $<

lib-update:
	git submodule update --init --remote $(LIB)
	$(M17BOARD) tables
	@echo "Library updated. Update the symbols and footprints in KiCad, then commit '$(LIB)'."

docker:
	docker run --rm -v "$(CURDIR)":/workspace -w /workspace -u "$$(id -u):$$(id -g)" \
		-e HOME=/tmp $(DOCKER_IMAGE) make all

clean:
	rm -rf $(OUT)

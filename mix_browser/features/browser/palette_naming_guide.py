from __future__ import annotations

from PySide6.QtCore import QT_TRANSLATE_NOOP
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout


_GUIDE_HTML = QT_TRANSLATE_NOOP("PaletteNamingGuideDialog", """
<p style="color:#b45309"><b>Verification warning:</b> This guide summarizes patterns in original game INI files and field descriptions documented by ModEnc. The examples have not been built as a mod or verified in-game.</p>
<p><b>Scope:</b> This guide explains how INI names refer to art sections,
graphics, and palette files. It is not a general list of every game asset.</p>

<h2>1. Use each field according to its meaning</h2>
<h3>Rules object <code>Image</code></h3>
<p>In <code>rules.ini</code> or <code>rulesmd.ini</code>, an object's
<code>Image</code> value selects an Art section: <code>Image=MYBUILDART</code>
selects Art <code>[MYBUILDART]</code>. If <code>Image</code> is omitted, the
game looks for an Art section with the same name as the Rules object. The value
is a section name, not a filename; do not add <code>.SHP</code>.</p>
<pre>; rulesmd.ini
[MYBUILDING]
Image=MYBUILDART

[MYTANK]
; Image omitted: this resolves to Art [MYTANK]

; artmd.ini
[MYBUILDART]

[MYTANK]</pre>

<h3>Art section <code>Image</code> and Voxel objects</h3>
<p>For SHP art, Art <code>Image</code> is the main graphic basename; the game
loads the SHP resource for that name. If it is omitted, the Art section name
is used. Keep the INI value and the file basename identical, ignoring the
<code>.SHP</code> extension.</p>
<p><code>Voxel=yes</code> is a format flag, not a filename. Set it in the Art
section resolved for the object. Each vehicle model part requires a VXL/HVA
pair with the same basename:</p>
<pre>; rulesmd.ini
[MYTANK]
Turret=yes

; artmd.ini
[MYTANK]
Voxel=yes

; vehicle body and turret resources
MYTANK.vxl
MYTANK.hva
MYTANKtur.vxl
MYTANKtur.hva</pre>
<p>When the vehicle has <code>Turret=yes</code>, add the literal suffix
<code>tur</code> to the model-family stem for the turret pair. If Rules uses
<code>Image=MYMODEL</code>, use <code>MYMODEL</code> as the model-family stem.
A missing turret pair can crash the game.</p>

<h3>Building voxel turrets and barrels</h3>
<p>Buildings use a different reference. Set <code>TurretAnim</code> to the
voxel resource basename and <code>TurretAnimIsVoxel=yes</code>; the value names
the VXL/HVA pair directly and does not require a corresponding Art section.
Voxel building turrets also require <code>NewTheater=yes</code>, or the turret
will not be drawn:</p>
<pre>; rulesmd.ini
[MYBUILDING]
NewTheater=yes
TurretAnim=MYTURRET
TurretAnimIsVoxel=yes

; resources
MYTURRET.vxl
MYTURRET.hva</pre>
<p>A building's voxel barrel uses <code>BarrelAnimIsVoxel=yes</code> together
with <code>VoxelBarrelFile</code>, which names that barrel resource. In the
usual case this makes <code>TurretAnim</code> use a SHP animation instead.
There is an exception when <code>TurretAnim</code> follows the building's
default turret naming convention, such as <code>[GTGCAN]</code> with
<code>TurretAnim=GTGCANTUR</code>; in that case
<code>BarrelAnimIsVoxel</code> does not take effect. See the ModEnc entries for
<a href="https://modenc.renegadeprojects.com/Turret">Turret</a>,
<a href="https://modenc.renegadeprojects.com/TurretAnim">TurretAnim</a>,
<a href="https://modenc.renegadeprojects.com/TurretAnimIsVoxel">TurretAnimIsVoxel</a>,
and <a href="https://modenc.renegadeprojects.com/BarrelAnimIsVoxel">BarrelAnimIsVoxel</a>.</p>

<h3><code>Cameo</code> and <code>AltCameo</code></h3>
<p>These Art fields name sidebar SHP files directly and omit the
<code>.SHP</code> extension. <code>Cameo</code> is the normal icon;
<code>AltCameo</code> is the veteran/elite icon. A common Westwood naming
pattern is an object code followed by <code>ICON</code> for the normal icon
and <code>UICO</code> for the elite icon:</p>
<pre>[GI]
Cameo=GIICON
AltCameo=GIUICO</pre>
<p>This is a common naming convention, not a mandatory filename format. If you
choose a different basename, put that exact basename in the field. Cameo documentation
describes filename matching as case-insensitive; case alone does not identify
a different cameo.</p>

<h3><code>Buildup</code>, <code>BibShape</code>, and animation references</h3>
<p><code>Buildup</code> and <code>BibShape</code> are direct SHP resource names,
not Art section names. For example, <code>Buildup=GAWEAPMK</code> refers to the
building-construction graphic <code>GAWEAPMK.SHP</code>; this field does not
require a separate <code>[GAWEAPMK]</code> Art section or an
<code>[Animations]</code> registry entry. <code>BibShape=GAWEAPBB</code>
similarly names <code>GAWEAPBB.SHP</code>. Do not assume
<code>NewTheater</code> applies to <code>BibShape</code>.</p>
<p>By contrast, <code>ActiveAnim</code> and its related building-animation
fields refer to names registered under <code>[Animations]</code> in Rules.
That name must also have the matching Art animation definition and image.
Registering an animation name and naming its SHP are separate steps.</p>
<pre>; rulesmd.ini
[Animations]
0=MYSPARK

; artmd.ini: animation definition and its graphic
[MYSPARK]
Image=MYSPARK

; artmd.ini: building Art section
[MYBUILDART]
ActiveAnim=MYSPARK</pre>
<p>This chain requires <code>MYSPARK.SHP</code> for the animation image. If the
Art animation section has its own <code>Image</code> override, use that value
for the SHP basename instead.</p>

<h3><code>SidebarImage</code></h3>
<p>For a Super Weapon, <code>SidebarImage</code> is in its Rules section and
names the sidebar SHP directly, without <code>.SHP</code>. For example,
<code>SidebarImage=IONCICON</code> refers to <code>IONCICON.SHP</code>. This is
not the same field as an object's Art <code>Cameo</code>.</p>

<h2>2. Name and attach palette files explicitly</h2>
<p>A palette is a separate <code>.PAL</code> resource. Its filename does not
automatically follow the SHP or VXL basename. First identify which INI field
owns the palette reference, then use that field's value format.</p>
<ul>
<li><b>Building Art <code>Palette</code>:</b> names the palette file for the
building's Art image. Its default is no explicit palette. Existing Art data
includes <code>Palette=lib</code>; the matching resource is <code>lib.pal</code>.
This field's observed value omits the extension.</li>
<li><b>Ares <code>CustomPalette</code>:</b> for animation/projectile art, the
documented value is a PAL filename including <code>.pal</code>, for example
<code>CustomPalette=MYANIM.pal</code>.</li>
<li><b>Ares particle <code>Palette</code>:</b> names the particle's PAL file,
including <code>.pal</code>; its documented default is <code>ANIM.PAL</code>.</li>
<li><b>Ares <code>SidebarPalette</code>:</b> sets the palette for that Super
Weapon's <code>SidebarImage</code>. Use the full filename, for example
<code>SidebarPalette=MYICON.pal</code>; the documented default is
<code>cameo.pal</code>.</li>
</ul>
<p>These are different INI scopes and their suffix conventions are not
interchangeable. In particular, <code>AltPalette</code>,
<code>AnimPalette</code>, and <code>TerrainPalette</code> are yes/no style
switches, not custom palette filenames. A palette setting selects a palette;
it does not rename the image or create the referenced PAL file.</p>

<h2>3. Keep theater variants as a file family</h2>
<p><code>NewTheater=yes</code> is a SHP naming rule: the second character of
the image basename is the theater marker. The documented examples identify
<code>A</code> as Arctic and <code>G</code> as Generic; RA2/YR theater families
also use markers such as <code>D</code> (Desert), <code>L</code> (Lunar),
<code>N</code> (New Urban), and <code>U</code> (Urban). Change only the theater
position and preserve the rest of the family name. Keep the Art section's
resource name and every variant consistent. A flag alone cannot turn
unrelated filenames into variants.</p>
<p><code>Theater=yes</code> is a different, older mechanism. It substitutes a
theater-specific extension for the normal SHP extension, such as
<code>.tem</code>, <code>.sno</code>, <code>.urb</code>, <code>.des</code>,
<code>.lun</code>, or <code>.ubn</code>. Do not treat it as a second-character
<code>NewTheater</code> family.</p>

<h2>4. Worked example and final checks</h2>
<p>This schematic building example uses an Art section name different from
both the object name and the graphic basename:</p>
<pre>; rulesmd.ini
[MYBUILDING]
Image=MYBUILDART

; artmd.ini
[MYBUILDART]
Image=MYBUILD
Cameo=MYICON
AltCameo=MYUICO
Palette=lib</pre>
<p>Package these matching resources:</p>
<pre>MYBUILD.SHP
MYICON.SHP
MYUICO.SHP
lib.pal</pre>
<ol>
<li>Confirm the Rules <code>Image</code> resolves to the intended Art section.</li>
<li>For each direct resource field, check the value against the real filename
and apply that field's extension rule.</li>
<li>For animation references, confirm the Rules registration, Art animation
section, and graphic all use the intended linked names.</li>
<li>For palette references, confirm the correct INI scope and whether its value
includes <code>.pal</code>; package that exact palette file.</li>
<li>When renaming, update every field that references the old name. Test the
complete INI and resource set in-game.</li>
</ol>
<p>INI comments are not active references. A filename written only after a
comment marker does not load an asset.</p>
""")


# @arch mix-browser.palette-naming-guide component | en: Explains how asset and palette filenames correspond to game INI references | zh: 说明资源文件名和色盘文件名如何对应游戏 INI 引用
class PaletteNamingGuideDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Filename Guide for INI Palette References"))
        self.resize(760, 680)
        self.setMinimumSize(560, 400)

        guide = QTextBrowser(self)
        guide.setOpenExternalLinks(True)
        guide.setHtml(self.tr(_GUIDE_HTML))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(guide, 1)
        layout.addWidget(buttons)

"""Write a terrain layer material (P_ccc-rrr_*.rvmat) the way Terrain Builder does.

Tiles are 512 m with 16 m overlap, stepping 480 m. Stage0/1 are the tile's
satellite and mask, mapped by world position; then three stages per surface
slot the cell uses (_ca, _nopx, _ca), numbered without gaps. The pixel shader
is TerrainN, N being the bitmask of the slots used.
"""

TILE, STEP, OVERLAP = 512, 480, 16
SIZE = 20480


def fnum(v):
    """Numbers as CfgConvert prints them (float32, up to 8 significant digits)."""
    import struct
    f = struct.unpack("<f", struct.pack("<f", v))[0]
    text = "%.8g" % f
    if "e" in text:
        text = "%g" % f
    return text


def uv_pos(col, row):
    return (OVERLAP - STEP * col) / TILE, (SIZE + OVERLAP - STEP * row) / TILE


VANILLA = "dz\\surfaces\\data\\terrain"


def layer_rvmat(prefix, col, row, slot_surfaces, folders=None):
    """slot_surfaces: surface class names of the slots this cell uses, in slot order,
    with None for an unused slot. folders: surface -> the folder of its textures
    (<name>_ca.paa, <name>_nopx.paa); vanilla's DZ\\surfaces\\data\\terrain by default,
    written as Terrain Builder writes it. Returns the rvmat text."""
    folders = folders or {}
    used = [i for i, s in enumerate(slot_surfaces) if s]
    shader = sum(1 << i for i in used)
    u0, v0 = uv_pos(col, row)
    inv = 1.0 / TILE
    tile = "%03d_%03d" % (col, row)
    out = []
    out.append("ambient[]={0.89999998,0.89999998,0.89999998,1};")
    out.append("diffuse[]={0.89999998,0.89999998,0.89999998,1};")
    out.append("forcedDiffuse[]={0.02,0.02,0.02,1};")
    out.append("emmisive[]={0,0,0,0};")
    out.append("specular[]={0,0,0,0};")
    out.append("specularPower=0;")
    out.append("class Stage0\n{\n\ttexture=\"%s\\data\\layers\\s_%s_lco.paa\";\n\ttexGen=3;\n};" % (prefix, tile))
    out.append("class Stage1\n{\n\ttexture=\"%s\\data\\layers\\m_%s_lco.paa\";\n\ttexGen=4;\n};" % (prefix, tile))
    world = ("\tuvSource=\"worldPos\";\n\tclass uvTransform\n\t{\n\t\taside[]={%s,0,0};\n\t\tup[]={0,0,%s};\n"
             "\t\tdir[]={0,%s,0};\n\t\tpos[]={%s,%s,0};\n\t};" % (fnum(inv), fnum(inv), fnum(-inv), fnum(u0), fnum(v0)))
    out.append("class TexGen3\n{\n%s\n};" % world)
    out.append("class TexGen4\n{\n%s\n};" % world)
    for n, scale in ((0, 1), (1, 10), (2, 10)):
        out.append("class TexGen%d\n{\n\tuvSource=\"tex\";\n\tclass uvTransform\n\t{\n\t\taside[]={%d,0,0};\n"
                   "\t\tup[]={0,%d,0};\n\t\tdir[]={0,0,%d};\n\t\tpos[]={0,0,0};\n\t};\n};" % (n, scale, scale, scale))
    out.append("PixelShaderID=\"Terrain%d\";" % shader)
    out.append("VertexShaderID=\"Terrain\";")
    stage = 2
    for i in used:
        s = slot_surfaces[i]
        folder = folders.get(s, VANILLA)
        if folder.lower() == VANILLA:
            paths = ("DZ\\surfaces\\data\\terrain\\%s_ca.paa", "dz\\surfaces\\data\\terrain\\%s_nopx.paa",
                     "dz\\surfaces\\data\\terrain\\%s_ca.paa")
        else:
            paths = (folder + "\\%s_ca.paa", folder + "\\%s_nopx.paa", folder + "\\%s_ca.paa")
        for path, gen in zip(paths, (0, 1, 2)):
            out.append("class Stage%d\n{\n\ttexture=\"%s\";\n\ttexGen=%d;\n};" % (stage, path % s, gen))
            stage += 1
    return "\n".join(out) + "\n"

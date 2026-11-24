"""Minimal stand-in for the compiled _surface extension on HarmonyOS.

The real module needs GLU's tessellator, which does not exist on OpenHarmony. ChimeraX uses it
for mesh operations; features that only colour or measure existing surfaces work without it, so
these entry points raise a clear error when a path actually needs tessellation.
"""


def _unavailable(name):
    def call(*args, **kwargs):
        raise NotImplementedError(
            "chimerax.surface._surface.%s is unavailable on HarmonyOS: the compiled "
            "extension needs GLU's tessellator" % name)
    call.__name__ = name
    return call


boundary_edge_mask = _unavailable("boundary_edge_mask")
boundary_edges = _unavailable("boundary_edges")
boundary_loops = _unavailable("boundary_loops")
calculate_vertex_normals = _unavailable("calculate_vertex_normals")
compute_cap = _unavailable("compute_cap")
connected_pieces = _unavailable("connected_pieces")
connected_triangles = _unavailable("connected_triangles")
estimate_surface_area_of_spheres = _unavailable("estimate_surface_area_of_spheres")
invert_vertex_normals = _unavailable("invert_vertex_normals")
refine_mesh = _unavailable("refine_mesh")
sharp_edge_patches = _unavailable("sharp_edge_patches")
smooth_vertex_positions = _unavailable("smooth_vertex_positions")
subdivide_triangles = _unavailable("subdivide_triangles")
surface_area_of_spheres = _unavailable("surface_area_of_spheres")
surface_distance = _unavailable("surface_distance")
triangle_vertices = _unavailable("triangle_vertices")
triangulate_polygon = _unavailable("triangulate_polygon")
unique_vertex_map = _unavailable("unique_vertex_map")
vertex_areas = _unavailable("vertex_areas")
vertex_convexity = _unavailable("vertex_convexity")

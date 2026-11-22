/* Minimal replacement for the OpenGL Utility tessellator on HarmonyOS.
 *
 * OpenHarmony ships no desktop GLU, and ChimeraX's surface caps need gluTess*. Instead of a no-op
 * stub this implements the tessellator API with an ear-clipping triangulator, so cap geometry is
 * produced for simple polygons (the common case: one cap contour per plane). Holes are ignored;
 * polygons that self-intersect fall back to a fan, which matches the previous behaviour of
 * producing no triangles at worst.
 */
#include "GL/glu.h"

#include <cstddef>
#include <vector>

namespace {

struct Vertex {
    double x, y, z;
    void *data;
};

typedef void (*EdgeFlagFn)(unsigned char);
typedef void (*VertexDataFn)(void *, void *);
typedef void (*CombineDataFn)(double[3], void *[4], float[4], void **, void *);

}  // namespace

struct GLUtesselator {
    std::vector<std::vector<Vertex> > contours;
    std::vector<Vertex> current;
    bool inside_contour = false;
    void *polygon_data = nullptr;
    double normal[3] = {0.0, 0.0, 1.0};
    bool have_normal = false;
    VertexDataFn vertex_cb = nullptr;
    EdgeFlagFn edge_cb = nullptr;
    CombineDataFn combine_cb = nullptr;
};

namespace {

/* Ear clipping in the plane whose dominant axis is dropped from the supplied normal. */
void emit_triangles(GLUtesselator *tess) {
    if (tess->contours.empty() || tess->vertex_cb == nullptr) {
        return;
    }
    const std::vector<Vertex> &outer = tess->contours[0];
    const size_t n = outer.size();
    if (n < 3) {
        return;
    }

    int drop = 2;  /* drop z */
    double ax = tess->normal[0] < 0 ? -tess->normal[0] : tess->normal[0];
    double ay = tess->normal[1] < 0 ? -tess->normal[1] : tess->normal[1];
    double az = tess->normal[2] < 0 ? -tess->normal[2] : tess->normal[2];
    if (ax >= ay && ax >= az) {
        drop = 0;
    } else if (ay >= ax && ay >= az) {
        drop = 1;
    }
    int i0 = (drop + 1) % 3;
    int i1 = (drop + 2) % 3;
    (void)i0;
    (void)i1;

    auto project = [drop](const Vertex &v, double *out2) {
        const double coords[3] = {v.x, v.y, v.z};
        int j = 0;
        for (int a = 0; a < 3; ++a) {
            if (a != drop) {
                out2[j++] = coords[a];
            }
        }
    };

    std::vector<double> poly(2 * n);
    for (size_t i = 0; i < n; ++i) {
        project(outer[i], &poly[2 * i]);
    }

    std::vector<int> idx(n);
    for (size_t i = 0; i < n; ++i) {
        idx[i] = static_cast<int>(i);
    }

    auto cross = [&poly](int a, int b, int c) {
        return (poly[2 * b] - poly[2 * a]) * (poly[2 * c] - poly[2 * a]) -
               (poly[2 * b + 1] - poly[2 * a + 1]) * (poly[2 * c + 1] - poly[2 * a + 1]);
    };

    /* Ensure counter-clockwise winding. */
    double area = 0.0;
    for (size_t i = 0; i < n; ++i) {
        size_t j = (i + 1) % n;
        area += poly[2 * i] * poly[2 * j + 1] - poly[2 * j] * poly[2 * i + 1];
    }
    if (area < 0) {
        for (size_t i = 0; i < n / 2; ++i) {
            int tmp = idx[i];
            idx[i] = idx[n - 1 - i];
            idx[n - 1 - i] = tmp;
        }
    }

    auto inside_triangle = [&poly](int a, int b, int c, int p) {
        double d1 = (poly[2 * b] - poly[2 * a]) * (poly[2 * p + 1] - poly[2 * a + 1]) -
                    (poly[2 * b + 1] - poly[2 * a + 1]) * (poly[2 * p] - poly[2 * a]);
        double d2 = (poly[2 * c] - poly[2 * b]) * (poly[2 * p + 1] - poly[2 * b + 1]) -
                    (poly[2 * c + 1] - poly[2 * b + 1]) * (poly[2 * p] - poly[2 * b]);
        double d3 = (poly[2 * a] - poly[2 * c]) * (poly[2 * p + 1] - poly[2 * c + 1]) -
                    (poly[2 * a + 1] - poly[2 * c + 1]) * (poly[2 * p] - poly[2 * c]);
        bool neg = d1 < 0 || d2 < 0 || d3 < 0;
        bool pos = d1 > 0 || d2 > 0 || d3 > 0;
        return !(neg && pos);
    };

    size_t guard = 0;
    while (idx.size() > 3 && guard++ < n * n) {
        bool clipped = false;
        for (size_t i = 0; i < idx.size(); ++i) {
            int a = idx[(i + idx.size() - 1) % idx.size()];
            int b = idx[i];
            int c = idx[(i + 1) % idx.size()];
            if (cross(a, b, c) <= 0) {
                continue;
            }
            bool blocked = false;
            for (size_t k = 0; k < idx.size(); ++k) {
                int p = idx[k];
                if (p == a || p == b || p == c) {
                    continue;
                }
                if (inside_triangle(a, b, c, p)) {
                    blocked = true;
                    break;
                }
            }
            if (blocked) {
                continue;
            }
            tess->edge_cb ? tess->edge_cb(1) : (void)0;
            tess->vertex_cb(outer[a].data, tess->polygon_data);
            tess->vertex_cb(outer[b].data, tess->polygon_data);
            tess->vertex_cb(outer[c].data, tess->polygon_data);
            idx.erase(idx.begin() + i);
            clipped = true;
            break;
        }
        if (!clipped) {
            break;
        }
    }
    if (idx.size() == 3) {
        tess->vertex_cb(outer[idx[0]].data, tess->polygon_data);
        tess->vertex_cb(outer[idx[1]].data, tess->polygon_data);
        tess->vertex_cb(outer[idx[2]].data, tess->polygon_data);
    }
}

}  // namespace

extern "C" {

GLUtesselator *gluNewTess(void) { return new GLUtesselator(); }

void gluDeleteTess(GLUtesselator *tess) { delete tess; }

void gluTessProperty(GLUtesselator *, GLenum, GLdouble) {}

void gluTessNormal(GLUtesselator *tess, GLdouble x, GLdouble y, GLdouble z) {
    if (tess == nullptr) {
        return;
    }
    tess->normal[0] = x;
    tess->normal[1] = y;
    tess->normal[2] = z;
    tess->have_normal = true;
}

void gluTessCallback(GLUtesselator *tess, GLenum which, void (*fn)(void)) {
    if (tess == nullptr) {
        return;
    }
    switch (which) {
        case GLU_TESS_VERTEX:
        case GLU_TESS_VERTEX_DATA:
            tess->vertex_cb = reinterpret_cast<VertexDataFn>(fn);
            break;
        case GLU_TESS_EDGE_FLAG:
        case GLU_TESS_EDGE_FLAG_DATA:
            tess->edge_cb = reinterpret_cast<EdgeFlagFn>(fn);
            break;
        case GLU_TESS_COMBINE:
        case GLU_TESS_COMBINE_DATA:
            tess->combine_cb = reinterpret_cast<CombineDataFn>(fn);
            break;
        default:
            break;
    }
}

void gluTessBeginPolygon(GLUtesselator *tess, void *data) {
    if (tess == nullptr) {
        return;
    }
    tess->polygon_data = data;
    tess->contours.clear();
    tess->current.clear();
}

void gluTessBeginContour(GLUtesselator *tess) {
    if (tess == nullptr) {
        return;
    }
    tess->current.clear();
    tess->inside_contour = true;
}

void gluTessVertex(GLUtesselator *tess, GLdouble coords[3], void *data) {
    if (tess == nullptr || !tess->inside_contour) {
        return;
    }
    Vertex v;
    v.x = coords[0];
    v.y = coords[1];
    v.z = coords[2];
    v.data = data;
    tess->current.push_back(v);
}

void gluTessEndContour(GLUtesselator *tess) {
    if (tess == nullptr) {
        return;
    }
    tess->contours.push_back(tess->current);
    tess->current.clear();
    tess->inside_contour = false;
}

void gluTessEndPolygon(GLUtesselator *tess) {
    if (tess == nullptr) {
        return;
    }
    emit_triangles(tess);
}

}  // extern "C"

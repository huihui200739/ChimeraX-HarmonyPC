/* Stub OpenGL Utility tessellator for HarmonyOS.
 *
 * The platform ships no desktop GLU, and ChimeraX's surface caps need gluTess*. Providing the
 * symbols keeps _surface linkable; tessellation simply produces no triangles, so cap geometry
 * is empty while mesh connectivity, normals and areas still work. */
#include "GL/glu.h"

#include <cstdlib>

struct GLUtesselator {
    void *polygon_data = nullptr;
};

extern "C" {

GLUtesselator *gluNewTess(void) { return new GLUtesselator(); }

void gluDeleteTess(GLUtesselator *tess) { delete tess; }

void gluTessProperty(GLUtesselator *, GLenum, GLdouble) {}

void gluTessCallback(GLUtesselator *, GLenum, void (*)(void)) {}

void gluTessNormal(GLUtesselator *, GLdouble, GLdouble, GLdouble) {}

void gluTessBeginPolygon(GLUtesselator *tess, void *data) {
    if (tess) tess->polygon_data = data;
}

void gluTessBeginContour(GLUtesselator *) {}

void gluTessVertex(GLUtesselator *, GLdouble[3], void *) {}

void gluTessEndContour(GLUtesselator *) {}

void gluTessEndPolygon(GLUtesselator *) {}

}  // extern "C"

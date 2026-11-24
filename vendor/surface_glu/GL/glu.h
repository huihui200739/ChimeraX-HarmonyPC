/* Minimal GLU tessellator declarations so ChimeraX's surface code compiles on HarmonyOS.
 * OpenHarmony has no desktop GLU; the implementation in glu_stub.cpp reports failure instead
 * of tessellating, which keeps the rest of the _surface module usable. */
#ifndef CX_GLU_STUB_H
#define CX_GLU_STUB_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct GLUtesselator GLUtesselator;
typedef double GLdouble;
typedef float GLfloat;
typedef unsigned char GLboolean;
typedef unsigned int GLenum;

#define GLU_TESS_BEGIN 100100
#define GLU_TESS_VERTEX 100101
#define GLU_TESS_END 100102
#define GLU_TESS_ERROR 100103
#define GLU_TESS_EDGE_FLAG 100104
#define GLU_TESS_COMBINE 100105
#define GLU_TESS_VERTEX_DATA 100106
#define GLU_TESS_BEGIN_DATA 100107
#define GLU_TESS_EDGE_FLAG_DATA 100108
#define GLU_TESS_END_DATA 100109
#define GLU_TESS_ERROR_DATA 100110
#define GLU_TESS_COMBINE_DATA 100111
#define GLU_TESS_WINDING_RULE 100140
#define GLU_TESS_WINDING_ODD 100130
#define GLU_TESS_WINDING_NONZERO 100131

GLUtesselator *gluNewTess(void);
void gluDeleteTess(GLUtesselator *tess);
void gluTessProperty(GLUtesselator *tess, GLenum which, GLdouble value);
void gluTessNormal(GLUtesselator *tess, GLdouble x, GLdouble y, GLdouble z);
void gluTessCallback(GLUtesselator *tess, GLenum which, void (*fn)(void));
void gluTessBeginPolygon(GLUtesselator *tess, void *data);
void gluTessBeginContour(GLUtesselator *tess);
void gluTessVertex(GLUtesselator *tess, GLdouble coords[3], void *data);
void gluTessEndContour(GLUtesselator *tess);
void gluTessEndPolygon(GLUtesselator *tess);

#ifdef __cplusplus
}
#endif

#endif

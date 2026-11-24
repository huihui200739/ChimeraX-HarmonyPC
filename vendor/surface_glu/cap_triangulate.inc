// CX_EARCUT: ear-clipping triangulation used in place of gluTess* on platforms without GLU.
// Triangles are emitted through vertex_data_callback(), matching the callback the rest of this
// file registers with the tessellator.
static void cx_emit_triangle(Polygon_Data &polygon_data, int a, int b, int c)
{
  vertex_data_callback(reinterpret_cast<void *>(a), &polygon_data);
  vertex_data_callback(reinterpret_cast<void *>(b), &polygon_data);
  vertex_data_callback(reinterpret_cast<void *>(c), &polygon_data);
}

static void triangulate_polygon(Loops &loops, float normal[3],
				Polygon_Data &polygon_data)
{
  if (loops.size() == 0)
    return;
  const Loop &outer = loops[0];
  int begin = outer.first, end = outer.second;
  int n = end - begin + 1;
  if (n < 3)
    return;

  // Drop the axis with the largest normal component so the polygon can be treated in 2D.
  int drop = 2;
  float ax = normal[0] < 0 ? -normal[0] : normal[0];
  float ay = normal[1] < 0 ? -normal[1] : normal[1];
  float az = normal[2] < 0 ? -normal[2] : normal[2];
  if (ax >= ay && ax >= az)
    drop = 0;
  else if (ay >= ax && ay >= az)
    drop = 1;

  std::vector<double> px(n), py(n);
  for (int i = 0 ; i < n ; ++i)
    {
      const float *p = &polygon_data.points[3 * (begin + i)];
      int j = 0;
      for (int a = 0 ; a < 3 ; ++a)
	{
	  if (a == drop)
	    continue;
	  if (j == 0) px[i] = p[a]; else py[i] = p[a];
	  ++j;
	}
    }

  std::vector<int> idx(n);
  for (int i = 0 ; i < n ; ++i)
    idx[i] = begin + i;

  // Ensure counter-clockwise winding.
  double area = 0.0;
  for (int i = 0 ; i < n ; ++i)
    {
      int j = (i + 1) % n;
      area += px[i] * py[j] - px[j] * py[i];
    }
  if (area < 0)
    {
      for (int i = 0 ; i < n / 2 ; ++i)
	{
	  int t = idx[i];
	  idx[i] = idx[n - 1 - i];
	  idx[n - 1 - i] = t;
	  double d = px[i];
	  px[i] = px[n - 1 - i];
	  px[n - 1 - i] = d;
	  d = py[i];
	  py[i] = py[n - 1 - i];
	  py[n - 1 - i] = d;
	}
    }

  std::vector<int> cur(n);
  for (int i = 0 ; i < n ; ++i) cur[i] = i;

  int guard = 0;
  while (int(cur.size()) > 3 && guard++ < n * n)
    {
      bool clipped = false;
      int m = int(cur.size());
      for (int s = 0 ; s < m ; ++s)
	{
	  int ia = cur[(s + m - 1) % m], ib = cur[s], ic = cur[(s + 1) % m];
	  double cross = (px[ib] - px[ia]) * (py[ic] - py[ia])
	    - (py[ib] - py[ia]) * (px[ic] - px[ia]);
	  if (cross <= 0)
	    continue;
	  bool blocked = false;
	  for (int t = 0 ; t < m ; ++t)
	    {
	      int ip = cur[t];
	      if (ip == ia || ip == ib || ip == ic)
		continue;
	      double d1 = (px[ib] - px[ia]) * (py[ip] - py[ia])
		- (py[ib] - py[ia]) * (px[ip] - px[ia]);
	      double d2 = (px[ic] - px[ib]) * (py[ip] - py[ib])
		- (py[ic] - py[ib]) * (px[ip] - px[ib]);
	      double d3 = (px[ia] - px[ic]) * (py[ip] - py[ic])
		- (py[ia] - py[ic]) * (px[ip] - px[ic]);
	      bool neg = d1 < 0 || d2 < 0 || d3 < 0;
	      bool pos = d1 > 0 || d2 > 0 || d3 > 0;
	      if (!(neg && pos))
		{
		  blocked = true;
		  break;
		}
	    }
	  if (blocked)
	    continue;
	  cx_emit_triangle(polygon_data, idx[ia], idx[ib], idx[ic]);
	  cur.erase(cur.begin() + s);
	  clipped = true;
	  break;
	}
      if (!clipped)
	break;
    }
  if (cur.size() == 3)
    cx_emit_triangle(polygon_data, idx[cur[0]], idx[cur[1]], idx[cur[2]]);
}

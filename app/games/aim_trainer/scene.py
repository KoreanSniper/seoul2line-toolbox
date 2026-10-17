"""Small CPU 3D renderer: world meshes, camera transform and frustum clipping."""
import math
from functools import lru_cache

from app.games.aim_trainer.model import dot, focal_length


def clip_polygon(points, planes):
    for plane in planes:
        output = []
        if not points:
            break
        previous = points[-1]
        previous_distance = dot(previous, plane[:3]) + plane[3]
        for current in points:
            distance = dot(current, plane[:3]) + plane[3]
            if (distance >= 0) != (previous_distance >= 0):
                t = previous_distance / (previous_distance - distance)
                output.append(tuple(a + t * (b - a) for a, b in zip(previous, current)))
            if distance >= 0:
                output.append(current)
            previous, previous_distance = current, distance
        points = output
    return points


def room_mesh():
    # Subdivided panels give the floor and walls stable perspective cues.
    faces = []
    for x in range(-6, 6, 2):
        for z in range(-8, 14, 2):
            color = '#28343e' if (x + z) % 4 else '#303e48'
            faces.append(([(x, 0, z), (x + 2, 0, z), (x + 2, 0, z + 2), (x, 0, z + 2)], color))
    for z in range(-8, 14, 2):
        for x in (-6, 6):
            faces.append(([(x, 0, z), (x, 4.8, z), (x, 4.8, z + 2), (x, 0, z + 2)], '#465463' if x < 0 else '#3d4a58'))
    for x in range(-6, 6, 2):
        for z in (-8, 14):
            faces.append(([(x, 0, z), (x, 4.8, z), (x + 2, 4.8, z), (x + 2, 0, z)], '#516071'))
    faces.append(([(-6, 4.8, -8), (6, 4.8, -8), (6, 4.8, 14), (-6, 4.8, 14)], '#202a34'))
    return faces


ROOM = room_mesh()


@lru_cache(maxsize=16)
def sphere_mesh(center, radius):
    faces = []
    rows, columns = 10, 16
    def vertex(row, column):
        latitude, longitude = math.pi * row / rows, math.tau * column / columns
        normal = (math.sin(latitude) * math.cos(longitude), math.cos(latitude), math.sin(latitude) * math.sin(longitude))
        return tuple(a + radius * b for a, b in zip(center, normal))
    for row in range(rows):
        for column in range(columns):
            points = [vertex(row, column), vertex(row + 1, column), vertex(row + 1, column + 1), vertex(row, column + 1)]
            normal = tuple((sum(point[axis] for point in points) / 4 - center[axis]) / radius for axis in range(3))
            light = .35 + .65 * max(0, dot(normal, (-.4, .7, -.59)))
            color = '#%02x%02x%02x' % (int(245 * light), int(112 * light), int(62 * light))
            faces.append((points, color))
    return faces


def render_faces(camera, target, radius, width, height, fov):
    focal = focal_length(width, fov)
    horizontal, vertical = width / (2 * focal), height / (2 * focal)
    planes = [(0, 0, 1, -.05), (1, 0, horizontal, 0), (-1, 0, horizontal, 0),
              (0, 1, vertical, 0), (0, -1, vertical, 0)]
    faces = []
    geometry = list(ROOM)
    if target is not None:
        for points, color in sphere_mesh(target, radius):
            middle = tuple(sum(point[axis] for point in points) / 4 for axis in range(3))
            normal = tuple(a - b for a, b in zip(middle, target))
            toward_camera = tuple(a - b for a, b in zip(camera.position, middle))
            if dot(normal, toward_camera) > 0:
                geometry.append((points, color))
    right, up, forward = camera.basis()
    position = camera.position
    for points, color in geometry:
        local = []
        for point in points:
            delta = tuple(a - b for a, b in zip(point, position))
            local.append((dot(delta, right), dot(delta, up), dot(delta, forward)))
        clipped = clip_polygon(local, planes)
        if len(clipped) < 3:
            continue
        screen = [(width / 2 + focal * x / z, height / 2 - focal * y / z) for x, y, z in clipped]
        faces.append((sum(point[2] for point in clipped) / len(clipped), screen, color))
    return sorted(faces, key=lambda face: face[0], reverse=True)

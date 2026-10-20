"""Lat/lon to UTM and Web Mercator, and a least-squares 2D similarity fit."""

import math

import numpy as np

A = 6378137.0
F = 1 / 298.257223563


def utm(lat, lon, zone):
    """WGS84 lat/lon (degrees) to UTM easting/northing (northern hemisphere)."""
    k0 = 0.9996
    e2 = F * (2 - F)
    ep2 = e2 / (1 - e2)
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    phi, lam = math.radians(lat), math.radians(lon)
    n = A / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = ep2 * math.cos(phi) ** 2
    a = math.cos(phi) * (lam - lon0)
    m = A * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
             - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
             + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
             - (35 * e2 ** 3 / 3072) * math.sin(6 * phi))
    x = k0 * n * (a + (1 - t + c) * a ** 3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * a ** 5 / 120) + 500000.0
    y = k0 * (m + n * math.tan(phi) * (a * a / 2 + (5 - t + 9 * c + 4 * c * c) * a ** 4 / 24
                                       + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * a ** 6 / 720))
    return x, y


def mercator(lat, lon):
    """WGS84 lat/lon to Web Mercator (EPSG:3857) metres."""
    return A * math.radians(lon), A * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def fit_similarity(src, dst):
    """Least-squares dst = s * R(theta) * src + t. Returns (s, theta, tx, ty, rms)."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    ms, md = src.mean(0), dst.mean(0)
    a, b = src - ms, dst - md
    sxx = (a * b).sum()
    sxy = (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]).sum()
    theta = math.atan2(sxy, sxx)
    s = math.hypot(sxx, sxy) / (a * a).sum()
    rot = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    t = md - s * rot @ ms
    res = dst - (s * (rot @ src.T).T + t)
    return s, theta, t[0], t[1], float(np.sqrt((res ** 2).sum(1).mean()))


def apply_similarity(fit, pts):
    s, theta, tx, ty = fit[:4]
    rot = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    return s * (rot @ np.asarray(pts, float).T).T + np.array([tx, ty])

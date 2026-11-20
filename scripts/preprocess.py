"""Clean a scanned page for OCR: binarize, deskew, remove table ruling lines.

usage: preprocess.py in.png out.png
"""
import sys
import cv2
import numpy as np


def deskew(bw):
    ys, xs = np.where(bw > 0)
    if len(xs) < 1000:
        return bw, 0.0
    angle = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))[-1]
    if angle > 45:
        angle -= 90
    if abs(angle) > 5 or abs(angle) < 0.1:
        return bw, 0.0
    h, w = bw.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(bw, m, (w, h), flags=cv2.INTER_NEAREST, borderValue=0), angle


def clean(gray):
    # ink = white on black for morphology
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 35, 15)
    bw, _ = deskew(bw)
    h, w = bw.shape
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, w // 25), 1)))
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(40, h // 40))))
    lines = cv2.dilate(horiz | vert, np.ones((3, 3), np.uint8))
    out = cv2.bitwise_and(bw, cv2.bitwise_not(lines))
    out = cv2.medianBlur(out, 3) if h > 2500 else out  # speckle removal at 300dpi
    return 255 - out


if __name__ == "__main__":
    g = cv2.imread(sys.argv[1], cv2.IMREAD_GRAYSCALE)
    cv2.imwrite(sys.argv[2], clean(g))

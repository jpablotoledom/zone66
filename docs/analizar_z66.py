#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# analizar_z66.py
#
# Script de apoyo para el analisis de Zone 66 (ver ANALISIS_DECOMPILACION.md).
# Compatible con Python 2.5 (no usa 'with', ni .format(), ni argparse,
# ni ninguna caracteristica posterior a 2.5).
#
# Uso:
#   python analizar_z66.py GAME.EXE
#   python analizar_z66.py OS.Z66 FONT.Z66 TITLE.Z66
#   python analizar_z66.py *.Z66            (con expansion de la shell)
#
# Para .EXE: parsea la cabecera MZ y calcula el offset de fichero del
# punto de entrada real (CS:IP), y el numero de entradas de reubicacion.
#
# Para .Z66: compara los primeros 4 bytes (uint32 little-endian, que
# el formato usa como tamano descomprimido) contra el tamano en disco,
# y calcula la entropia de Shannon del fichero completo en bits/byte.
# 
# 
# Creado por: Jonathan Toledo

import struct
import math
import os
import sys


def parse_mz_header(path):
    f = open(path, "rb")
    raw = f.read(28)
    f.close()
    if len(raw) < 28:
        raise ValueError("fichero demasiado pequeno para ser un EXE: " + path)
    fields = struct.unpack("<2s13H", raw)
    sig = fields[0]
    e_cblp = fields[1]
    e_cp = fields[2]
    e_crlc = fields[3]
    e_cparhdr = fields[4]
    e_ip = fields[10]
    e_cs = fields[11]
    if sig != "MZ":
        raise ValueError("no es un ejecutable MZ: " + path)
    header_bytes = e_cparhdr * 16
    entry_offset = header_bytes + e_ip
    return {
        "cblp": e_cblp,
        "cp": e_cp,
        "crlc": e_crlc,
        "cparhdr": e_cparhdr,
        "ip": e_ip,
        "cs": e_cs,
        "header_bytes": header_bytes,
        "entry_offset": entry_offset,
    }


def shannon_entropy(data):
    if len(data) == 0:
        return 0.0
    counts = [0] * 256
    for ch in data:
        counts[ord(ch)] += 1
    total = len(data)
    entropy = 0.0
    for c in counts:
        if c:
            p = float(c) / total
            entropy -= p * math.log(p, 2)
    return entropy


def z66_declared_size(data):
    if len(data) < 4:
        return None
    return struct.unpack("<I", data[0:4])[0]


def analizar_exe(path):
    h = parse_mz_header(path)
    print "%s (MZ):" % path
    print "  cabecera         = %d bytes (%d parrafos)" % (h["header_bytes"], h["cparhdr"])
    print "  CS:IP inicial    = %04X:%04X" % (h["cs"], h["ip"])
    print "  offset de fichero del punto de entrada = 0x%X" % h["entry_offset"]
    print "  entradas de reubicacion (e_crlc) = %d" % h["crlc"]


def analizar_z66(path):
    f = open(path, "rb")
    data = f.read()
    f.close()
    disk_size = len(data)
    declared = z66_declared_size(data)
    entropy = shannon_entropy(data)
    print "%s (.Z66):" % path
    print "  tamano en disco       = %d bytes" % disk_size
    if declared is not None and disk_size > 0:
        ratio = float(declared) / disk_size
        print "  tamano declarado(4B)  = %d bytes" % declared
        print "  ratio declarado/disco = %.2fx" % ratio
        if ratio < 1.05:
            print "  nota: ratio ~1.0 -> probablemente sin comprimir (PCM/config)"
    print "  entropia              = %.2f bits/byte" % entropy
    if entropy > 7.5:
        print "  nota: entropia muy alta -> compatible con stream comprimido"
    elif entropy < 6.0:
        print "  nota: entropia baja -> compatible con datos con patrones (tiles, texto)"


def analizar(path):
    ext = os.path.splitext(path)[1].upper()
    if ext == ".EXE":
        analizar_exe(path)
    elif ext == ".Z66":
        analizar_z66(path)
    else:
        print "%s: extension no reconocida (se esperaba .EXE o .Z66)" % path


def main():
    if len(sys.argv) < 2:
        print "uso: python analizar_z66.py fichero1 [fichero2 ...]"
        sys.exit(1)
    for path in sys.argv[1:]:
        try:
            analizar(path)
        except (IOError, ValueError), e:
            print "%s: ERROR: %s" % (path, e)
        print ""


if __name__ == "__main__":
    main()

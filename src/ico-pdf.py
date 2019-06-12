#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier:     MIT

"""
    Creates polyglot files that are valid ICO images
    as well as PDF documents.

    :copyright: © 2019, tickelton <tickelton@gmail.com>.
    :license: MIT, see LICENSE for details.
"""

import os
import re
import sys
import struct
import logging

# typedef struct
# {
#     WORD           idReserved;   // Reserved (must be 0)
#     WORD           idType;       // Resource Type (1 for icons)
#     WORD           idCount;      // How many images?
#     ICONDIRENTRY   idEntries[1]; // An entry for each image (idCount of 'em)
# } ICONDIR, *LPICONDIR;
LEN_ICONDIR = 6
ICONDIR = '<HHH'
ID_RESERVED = 0
ID_TYPE = 1
ID_COUNT = 2

# typedef struct
# {
#     BYTE        bWidth;          // Width, in pixels, of the image
#     BYTE        bHeight;         // Height, in pixels, of the image
#     BYTE        bColorCount;     // Number of colors in image (0 if >=8bpp)
#     BYTE        bReserved;       // Reserved ( must be 0)
#     WORD        wPlanes;         // Color Planes
#     WORD        wBitCount;       // Bits per pixel
#     DWORD       dwBytesInRes;    // How many bytes in this resource?
#     DWORD       dwImageOffset;   // Where in the file is this image?
# } ICONDIRENTRY, *LPICONDIRENTRY;
LEN_ICONDIRENTRY = 16
ICONDIRENTRY = '<BBBBHHII'
BWIDTH = 0
BHEIGHT = 1
BCOLORCOUNT = 2
BRESERVED = 3
WPLANES = 4
WBITCOUNT = 5
DWBYTESINRES = 6
DWIMAGEOFFSET = 7

###############################
# format of PDF stream object #
###############################
# 9999 0 obj                  #
# <<                          #
# /Length 15                  #
# >>                          #
# stream                      #
# FOOOOOOOOOOOOOO             #
# endstream                   #
# endobj                      #
###############################
FIRSTFREEID = 0
OFFSETLASTSTREAM = 1
OBJSTREAM_HEAD = """{} 0 obj <<
/Length {}       
>>
stream
"""
OBJSTREAM_TAIL = """
endstream
endobj
"""

verbose = False

def usage():
    print("Usage: {} [-h] [-v] [--help] ICOFILE PDFFILE OUTFILE".format(sys.argv[0]))
    print("  -h, --help      : print this help message")
    print("  -v              : verbose output")
    print("  ICOFILE         : input ico file")
    print("  PDFFILE         : input pdf file")
    print("  OUTFILE         : output file name")

def parse_args():
    global verbose

    argc = len(sys.argv)
    if argc < 4 or argc > 5:
        usage()
        sys.exit(1)

    for i in range(1, argc):
        if sys.argv[i] == '-v':
            verbose = True
        if sys.argv[i] == '-h' or sys.argv[i] == '--help':
            usage()
            sys.exit(0)

    if verbose and argc == 4:
        usage()
        sys.exit(1)

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    return (sys.argv[-3], sys.argv[-2], sys.argv[-1])

def icondir_valid(icondir):
    if icondir[ID_RESERVED] != 0:
        logging.error("Invalid ico file.")
        logging.debug("ICONDIR.idReserved: got {}, expected 0".format(
            icondir[ID_RESERVED])
        )
        return False
    if icondir[ID_TYPE] != 1:
        logging.error("Invalid ico file.")
        logging.debug("ICONDIR.idType: got {}, expected 1".format(
            icondir[ID_TYPE])
        )
        return False
    if icondir[ID_COUNT] < 1 or icondir[ID_COUNT] > 10:
        logging.error("Unsupported number of images in ico file: {}".format(
            icondir[ID_COUNT])
        )
        return False

    return True

def icondirentry_valid(entry, icosize):
    if entry[BWIDTH] < 0 or entry[BWIDTH] > 255:
        logging.error("Unexpected image width ({})".format(entry[BWIDTH]))
        return False

    if entry[BHEIGHT] < 0 or entry[BHEIGHT] > 255:
        logging.error("Unexpected image height ({})".format(entry[BHEIGHT]))
        return False

    if entry[BRESERVED] != 0 and entry[BRESERVED] != 255:
        logging.warning("bReserved should be 0 or 255, is {}".format(
            entry[BRESERVED])
        )

    if entry[WPLANES] != 0 and entry[WPLANES] != 1:
        logging.warning(
                "Unexpected value in wPlanes ({}). Is this a CUR file?".format(
                    entry[WPLANES])
        )

    if entry[DWBYTESINRES] + entry[DWIMAGEOFFSET] > icosize:
        logging.error("Image offset > file size({}+{}>{})".format(
            entry[DWBYTESINRES],
            entry[DWIMAGEOFFSET],
            icosize)
        )
        return False

    return (entry[DWBYTESINRES], entry[DWIMAGEOFFSET])

def ico_valid(f, icosize):
    icondir = struct.unpack(ICONDIR, f.read(LEN_ICONDIR))
    logging.debug("icondir={}".format(icondir))

    if not icondir_valid(icondir):
        return (0, [])

    icondirentries = []
    for i in range(icondir[ID_COUNT]):
        icondirentries.append(icondirentry_valid(
            struct.unpack(ICONDIRENTRY, f.read(LEN_ICONDIRENTRY)),
            icosize)
        )

        if icondirentries[i] == False:
            return (0, [])

    logging.debug("icondirentries={}".format(icondirentries))

    return (icondir[ID_COUNT], icondirentries)

def pdf_valid(f):
    start_valid = False
    # find b'%PDF-' in first 1024 bytes
    for i in range(1024):
        f.seek(i, 0)
        tmp = f.read(5)
        if tmp == b'%PDF-':
            start_valid = True
            break

    end_valid = False
    # find b'%%EOF' in last 1024 bytes
    for i in range(-4, -1024, -1):
        f.seek(i, 2)
        tmp = f.read(5)
        if tmp == b'%%EOF':
            end_valid = True
            break

    if start_valid and end_valid:
        return True
    elif not start_valid:
        logging.error("PDF header (%PDF) not found in first 1024 bytes of file")
    else:
        logging.error("PDF trailer (%%EOF) not found in last 1024 bytes of file")

    return False

def id_range_free(obj_ids, ico_count, cur_id):
    for i in range(ico_count):
        if cur_id + i in obj_ids:
            return False

    return True

def get_free_id(obj_ids, ico_count):
    for cur_id in range(990, 9999-ico_count):
        if id_range_free(obj_ids, ico_count, cur_id):
            return cur_id

    return 0

def get_pdf_params(f, pdfsize, ico_count):
    f.seek(0, 0)

    obj_ids = []
    for line in f:
        m = re.match(b'(\d+) \d+ obj', line)
        if m:
            obj_ids.append(int(m.group(1)))

    if not obj_ids:
        logging.error("No object IDs found. Is this a valid PDF file?")
        return None

    first_free_id = get_free_id(obj_ids, ico_count)
    if not first_free_id:
        logging.error("No usable object IDs found in PDF.")
        return None

    offset_last_stream = 0
    for i in range(-6, -pdfsize, -1):
        f.seek(i, 2)
        tmp = f.read(6)
        if tmp == b'endobj':
            offset_last_stream = f.tell() + 1
            break

    if not offset_last_stream:
        logging.error("Could not determine stream offset in PDF.")
        return None

    return (first_free_id, offset_last_stream)

def write_ico_header(icofile, ico_count, outfile):
    icofile.seek(0, 0)
    outfile.seek(0, 0)

    try:
        outfile.write(icofile.read(LEN_ICONDIR))
        for i in range(ico_count):
            outfile.write(icofile.read(LEN_ICONDIRENTRY))
    except IOError as ie:
        print("Error writing file: {}".format(ie))
        return False

    return True

def write_pdf_header(pdffile, pdf_params, outfile):
    pdffile.seek(0, 0)
    outfile.seek(0, 2)

    try:
        outfile.write(pdffile.read(pdf_params[OFFSETLASTSTREAM]))
    except IOError as ie:
        print("Error writing file: {}".format(ie))
        return False

    return True

def write_pdf_trailer(pdffile, pdf_params, outfile):
    pdffile.seek(pdf_params[OFFSETLASTSTREAM], 0)
    outfile.seek(0, 2)

    try:
        outfile.write(pdffile.read())
    except IOError as ie:
        print("Error writing file: {}".format(ie))
        return False

    return True

def write_ico_streams(icofile, ico_data, pdf_params, outfile):
    outfile.seek(0, 2)

    ico_offsets = []
    obj_id = pdf_params[0]
    for i in ico_data:
        logging.debug("Writing image at {} with length {} with id {}.".format(
            i[1], i[0], obj_id)
        )

        try:
            outfile.write(OBJSTREAM_HEAD.format(obj_id, i[0]).encode('utf-8'))
            icofile.seek(i[1], 0)
            ico_offsets.append(outfile.tell())
            outfile.write(icofile.read(i[0]))
            outfile.write(OBJSTREAM_TAIL.encode('utf-8'))
        except IOError as ie:
            print("Error writing file: {}".format(ie))
            return []

        logging.debug("Image data written at {}.".format(
            ico_offsets[-1])
        )

        obj_id += 1

    return ico_offsets

def fix_ico_offsets(outfile, ico_offsets):
    # seek to first image size in header
    outfile.seek(18, 0)

    for i in ico_offsets:
        try:
            outfile.write(struct.pack('<I', i))
        except IOError as ie:
            print("Error writingfile: {}".format(ie))
            return False

        outfile.seek(12, 1)

    return True

if __name__ == "__main__":
    (iconame, pdfname, outname) = parse_args()
    logging.debug("ico={} pdf={} out={}".format(iconame, pdfname, outname))

    if os.path.exists(outname):
        logging.error("{} already exists.".format(outname))
        sys.exit(1)

    try:
        icofile = open(iconame, 'rb')
    except IOError as ie:
        print("Error opening ico file: {}".format(ie))
        sys.exit(1)

    icosize = os.path.getsize(iconame)
    (ico_count, ico_data) = ico_valid(icofile, icosize)
    if not ico_count:
        icofile.close()
        sys.exit(1)

    try:
        pdffile = open(pdfname, 'rb')
    except IOError as ie:
        print("Error opening pdf file: {}".format(ie))
        icofile.close()
        sys.exit(1)

    if not pdf_valid(pdffile):
        pdffile.close()
        icofile.close()
        sys.exit(1)

    pdfsize = os.path.getsize(pdfname)
    pdf_params = get_pdf_params(pdffile, pdfsize, ico_count)
    if not pdf_params:
        pdffile.close()
        icofile.close()
        sys.exit(1)

    logging.debug("pdf_params={}".format(pdf_params))

    try:
        outfile = open(outname, 'wb')
    except IOError as ie:
        print("Error opening output file: {}".format(ie))
        pdffile.close()
        icofile.close()
        sys.exit(1)

    if not write_ico_header(icofile, ico_count, outfile):
        outfile.close()
        pdffile.close()
        icofile.close()
        sys.exit(1)

    if not write_pdf_header(pdffile, pdf_params, outfile):
        outfile.close()
        pdffile.close()
        icofile.close()
        sys.exit(1)

    ico_offsets = write_ico_streams(icofile, ico_data, pdf_params, outfile)
    if not ico_offsets:
        outfile.close()
        pdffile.close()
        icofile.close()
        sys.exit(1)

    if not write_pdf_trailer(pdffile, pdf_params, outfile):
        outfile.close()
        pdffile.close()
        icofile.close()
        sys.exit(1)

    if not fix_ico_offsets(outfile, ico_offsets):
        outfile.close()
        pdffile.close()
        icofile.close()
        sys.exit(1)

    print("Output file successfully written.")

    outfile.close()
    pdffile.close()
    icofile.close()

    sys.exit(0)

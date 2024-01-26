#!/bin/sh
# required: https://github.com/flother/spreet
mkdir .sprites
cp symbols/occupation/* .sprites/
cp -r symbols/detailed/ .sprites/
cp -r symbols/simple/ .sprites/
spreet .sprites --recursive --retina -m sprite@2x
spreet .sprites --recursive -m sprite
rm -fr .sprites

cp sprite* ../../../static/huts/
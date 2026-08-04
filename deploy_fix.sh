#!/bin/bash
cd /Users/hakan/Desktop/sesbot
python3 scripts/deploy_vercel.py --token "$VERCEL_TOKEN" --skip-build

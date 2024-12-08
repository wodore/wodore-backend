#!/bin/bash

ENVIRONMENT="dev"

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --env) ENVIRONMENT="$2"; shift ;;
        *) echo "Unknown option: $1" ;;
    esac
    shift
done

infisical export --env="$ENVIRONMENT" --path /backend --silent | sed "s/='\(.*\)'$/=\1/"
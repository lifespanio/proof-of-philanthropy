#!/bin/sh

gramine-sgx-get-token --output update.token --sig update.sig
gramine-sgx update


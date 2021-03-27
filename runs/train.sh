export CUDA_VISIBLE_DEVICES=0

CONFIG_PATH=configs/custom.json
VERBOSE="yes"

python train.py -c $CONFIG_PATH -v $VERBOSE

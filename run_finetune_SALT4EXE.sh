WORKSPACE="your_workspace"
DATA_PATH="${WORKSPACE}/SFT_dataset_path"
OUTPUT_PATH="${WORKSPACE}/output_models/your_model_name"
MODEL_PATH="LLM4Binary/llm4decompile-6.7b-v1.5"

deepspeed --include localhost:0,1,2 --master_port 61472 finetune_drop.py \
    --model_name_or_path $MODEL_PATH \
    --data_path $DATA_PATH \
    --output_dir $OUTPUT_PATH \
    --num_train_epochs 1 \
    --model_max_length 4096 \
    --per_device_train_batch_size 8 \
    --gradient_accumulation_steps 16 \
    --evaluation_strategy "no" \
    --save_strategy "epoch" \
    --use_flash_attention \
    --save_steps 800 \
    --save_total_limit 100 \
    --learning_rate 5e-6 \
    --max_grad_norm 1.0 \
    --weight_decay 0.01 \
    --warmup_ratio 0.025 \
    --logging_steps 1 \
    --lr_scheduler_type "cosine" \
    --gradient_checkpointing True \
    --deepspeed configs/ds_config_zero3.json \
    --report_to "tensorboard" \
    --bf16 True
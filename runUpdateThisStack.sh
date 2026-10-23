#!/bin/bash



# STEP 1: Create necessary files and directories
# ==============================================
mkdir -p ./_DATA/fullnode
mkdir -p ./_DATA/exchange
sudo chown -R 1000:1000 ./_DATA




# STEP 2: Generate exchange private key if it doesn't exist
# =========================================================
if [ ! -f .env ] || ! grep -q "^EXCHANGE_PRIVATE_KEY=" .env; then
    echo "Generating EXCHANGE_PRIVATE_KEY..."
    EXCHANGE_PRIVATE_KEY="$(openssl rand -hex 32)"

    # Only add newline if file doesn't end with one
    [ -f .env ] && [ -n "$(tail -c1 .env 2>/dev/null)" ] && echo "" >> .env
    echo "EXCHANGE_PRIVATE_KEY=$EXCHANGE_PRIVATE_KEY" >> .env
    echo "EXCHANGE_PRIVATE_KEY added to .env"
fi




# STEP 3: Generate DBGATE_PASSWORD if it doesn't exist
# ====================================================
if [ ! -f .env ] || ! grep -q "^DBGATE_PASSWORD=" .env; then
    echo "Generating DBGATE_PASSWORD..."
    DBGATE_PASSWORD="$(openssl rand -hex 32)"

    # Only add newline if file doesn't end with one
    [ -f .env ] && [ -n "$(tail -c1 .env 2>/dev/null)" ] && echo "" >> .env
    echo "DBGATE_PASSWORD=$DBGATE_PASSWORD" >> .env
    echo "DBGATE_PASSWORD added to .env"
fi




# STEP 4: Run the stack
# =====================
sudo docker network create --subnet=172.18.0.0/24 external
sudo docker-compose down --timeout=60
sudo docker-compose up -d --build



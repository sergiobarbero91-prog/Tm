#!/bin/bash
# =============================================================================
# MongoDB Backup Script for TaxiDash Madrid
# =============================================================================
# Usage: ./backup_mongodb.sh [full|incremental]
# 
# Creates timestamped backups of the MongoDB database
# Keeps last 7 daily backups and last 4 weekly backups
# =============================================================================

set -e

# Configuration
DB_NAME="test_database"
BACKUP_DIR="/app/backups"
DATE=$(date +%Y%m%d_%H%M%S)
DAY_OF_WEEK=$(date +%u)  # 1=Monday, 7=Sunday
BACKUP_TYPE="${1:-full}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}  TaxiDash MongoDB Backup${NC}"
echo -e "${GREEN}  $(date)${NC}"
echo -e "${GREEN}=========================================${NC}"

# Create backup directories
mkdir -p "$BACKUP_DIR/daily"
mkdir -p "$BACKUP_DIR/weekly"

# Determine backup destination
if [ "$DAY_OF_WEEK" -eq 7 ]; then
    # Sunday = weekly backup
    BACKUP_PATH="$BACKUP_DIR/weekly/backup_${DATE}"
    echo -e "${YELLOW}Creating WEEKLY backup...${NC}"
else
    BACKUP_PATH="$BACKUP_DIR/daily/backup_${DATE}"
    echo -e "${YELLOW}Creating DAILY backup...${NC}"
fi

# Create the backup using mongodump
echo "Database: $DB_NAME"
echo "Destination: $BACKUP_PATH"
echo ""

if mongodump --db="$DB_NAME" --out="$BACKUP_PATH" 2>/dev/null; then
    echo -e "${GREEN}✓ Backup created successfully${NC}"
    
    # Compress the backup
    echo "Compressing backup..."
    cd "$BACKUP_DIR"
    if [ "$DAY_OF_WEEK" -eq 7 ]; then
        tar -czf "weekly/backup_${DATE}.tar.gz" -C "weekly" "backup_${DATE}"
        rm -rf "weekly/backup_${DATE}"
        FINAL_PATH="weekly/backup_${DATE}.tar.gz"
    else
        tar -czf "daily/backup_${DATE}.tar.gz" -C "daily" "backup_${DATE}"
        rm -rf "daily/backup_${DATE}"
        FINAL_PATH="daily/backup_${DATE}.tar.gz"
    fi
    
    # Get backup size
    BACKUP_SIZE=$(du -h "$BACKUP_DIR/$FINAL_PATH" | cut -f1)
    echo -e "${GREEN}✓ Backup compressed: $BACKUP_SIZE${NC}"
    
    # Cleanup old backups
    echo ""
    echo "Cleaning up old backups..."
    
    # Keep only last 7 daily backups
    cd "$BACKUP_DIR/daily"
    ls -t *.tar.gz 2>/dev/null | tail -n +8 | xargs -r rm -f
    DAILY_COUNT=$(ls -1 *.tar.gz 2>/dev/null | wc -l)
    echo "  Daily backups kept: $DAILY_COUNT"
    
    # Keep only last 4 weekly backups
    cd "$BACKUP_DIR/weekly"
    ls -t *.tar.gz 2>/dev/null | tail -n +5 | xargs -r rm -f
    WEEKLY_COUNT=$(ls -1 *.tar.gz 2>/dev/null | wc -l)
    echo "  Weekly backups kept: $WEEKLY_COUNT"
    
    echo ""
    echo -e "${GREEN}=========================================${NC}"
    echo -e "${GREEN}  Backup Complete!${NC}"
    echo -e "${GREEN}  File: $FINAL_PATH${NC}"
    echo -e "${GREEN}  Size: $BACKUP_SIZE${NC}"
    echo -e "${GREEN}=========================================${NC}"
    
else
    echo -e "${RED}✗ Backup failed!${NC}"
    exit 1
fi

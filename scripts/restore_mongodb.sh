#!/bin/bash
# =============================================================================
# MongoDB Restore Script for TaxiDash Madrid
# =============================================================================
# Usage: ./restore_mongodb.sh <backup_file.tar.gz>
# 
# Restores a MongoDB backup from a compressed archive
# =============================================================================

set -e

# Configuration
DB_NAME="test_database"
BACKUP_DIR="/app/backups"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ -z "$1" ]; then
    echo -e "${RED}Error: Please specify a backup file${NC}"
    echo ""
    echo "Usage: $0 <backup_file.tar.gz>"
    echo ""
    echo "Available backups:"
    echo ""
    echo "Daily backups:"
    ls -lh "$BACKUP_DIR/daily/"*.tar.gz 2>/dev/null || echo "  (none)"
    echo ""
    echo "Weekly backups:"
    ls -lh "$BACKUP_DIR/weekly/"*.tar.gz 2>/dev/null || echo "  (none)"
    exit 1
fi

BACKUP_FILE="$1"

# Check if file exists
if [ ! -f "$BACKUP_FILE" ]; then
    # Try to find it in backup directories
    if [ -f "$BACKUP_DIR/daily/$BACKUP_FILE" ]; then
        BACKUP_FILE="$BACKUP_DIR/daily/$BACKUP_FILE"
    elif [ -f "$BACKUP_DIR/weekly/$BACKUP_FILE" ]; then
        BACKUP_FILE="$BACKUP_DIR/weekly/$BACKUP_FILE"
    else
        echo -e "${RED}Error: Backup file not found: $BACKUP_FILE${NC}"
        exit 1
    fi
fi

echo -e "${YELLOW}=========================================${NC}"
echo -e "${YELLOW}  TaxiDash MongoDB Restore${NC}"
echo -e "${YELLOW}  $(date)${NC}"
echo -e "${YELLOW}=========================================${NC}"
echo ""
echo -e "${RED}WARNING: This will overwrite the current database!${NC}"
echo "Backup file: $BACKUP_FILE"
echo ""
read -p "Are you sure you want to continue? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Restore cancelled."
    exit 0
fi

# Create temp directory for extraction
TEMP_DIR=$(mktemp -d)
echo ""
echo "Extracting backup..."

# Extract the backup
tar -xzf "$BACKUP_FILE" -C "$TEMP_DIR"

# Find the extracted directory
EXTRACTED_DIR=$(find "$TEMP_DIR" -maxdepth 1 -type d -name "backup_*" | head -1)

if [ -z "$EXTRACTED_DIR" ]; then
    echo -e "${RED}Error: Could not find backup data in archive${NC}"
    rm -rf "$TEMP_DIR"
    exit 1
fi

echo "Restoring database..."

# Restore using mongorestore
if mongorestore --db="$DB_NAME" --drop "$EXTRACTED_DIR/$DB_NAME" 2>/dev/null; then
    echo -e "${GREEN}✓ Database restored successfully!${NC}"
else
    echo -e "${RED}✗ Restore failed!${NC}"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# Cleanup
rm -rf "$TEMP_DIR"

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}  Restore Complete!${NC}"
echo -e "${GREEN}=========================================${NC}"

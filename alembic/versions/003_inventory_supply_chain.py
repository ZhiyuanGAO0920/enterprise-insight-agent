"""库存与供应链表 —— V3 P3 扩展。

修订 ID: 003_inventory_supply_chain
创建日期: 2026-06-10

所有表使用 IF NOT EXISTS —— 可安全地在运行中的 V2 数据库上执行。
无 ALTER/DROP/RENAME 操作。V2 代码完全不受影响。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003_inventory_supply_chain"
down_revision: Union[str, None] = "002_v3_new_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- V4 补充：V2 基础业务表（全新安装时需创建） ----
    op.execute("""
        CREATE TABLE IF NOT EXISTS store (
            id SERIAL PRIMARY KEY,
            store_name VARCHAR(200) NOT NULL,
            region VARCHAR(100) NOT NULL,
            manager VARCHAR(100),
            status VARCHAR(20) DEFAULT 'active',
            create_time TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id SERIAL PRIMARY KEY,
            store_id INT REFERENCES store(id),
            create_time TIMESTAMP NOT NULL DEFAULT NOW(),
            amount DECIMAL(12,2) NOT NULL DEFAULT 0,
            refund_amount DECIMAL(12,2) DEFAULT 0,
            member_id INT REFERENCES member(member_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS member (
            member_id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            level VARCHAR(50) NOT NULL DEFAULT '普通会员',
            phone VARCHAR(20),
            email VARCHAR(200),
            channel VARCHAR(50),
            age_group VARCHAR(20),
            gender VARCHAR(10),
            register_date TIMESTAMP NOT NULL DEFAULT NOW(),
            last_consume_date TIMESTAMP,
            total_amount DECIMAL(12,2) NOT NULL DEFAULT 0
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS employee_performance (
            id SERIAL PRIMARY KEY,
            store_id INT REFERENCES store(id),
            employee_name VARCHAR(100) NOT NULL,
            month VARCHAR(7) NOT NULL,
            sales_amount DECIMAL(12,2) DEFAULT 0,
            orders_count INT DEFAULT 0
        )
    """)

    # ---- V4: Store 种子数据 ----
    op.execute("""
        INSERT INTO store (id, name, store_name, region, manager, status) VALUES
        (1, '上海旗舰店', '上海旗舰店', '华东', '张经理', 'active'),
        (2, '北京中心店', '北京中心店', '华北', '王经理', 'active'),
        (3, '广州旗舰店', '广州旗舰店', '华南', '陈经理', 'active')
        ON CONFLICT (id) DO NOTHING
    """)

    # ---- 供应商 (supplier) ----
    op.execute("""
        CREATE TABLE IF NOT EXISTS supplier (
            id SERIAL PRIMARY KEY,
            supplier_name VARCHAR(200) NOT NULL,
            category VARCHAR(100) NOT NULL,
            contact VARCHAR(100),
            phone VARCHAR(20),
            lead_time_days INT DEFAULT 7,
            on_time_rate DECIMAL(5,2) DEFAULT 100.00,
            quality_score DECIMAL(3,1) DEFAULT 5.0,
            status VARCHAR(20) DEFAULT 'active',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # ---- 商品 (product) ----
    op.execute("""
        CREATE TABLE IF NOT EXISTS product (
            id SERIAL PRIMARY KEY,
            product_name VARCHAR(200) NOT NULL,
            category VARCHAR(100) NOT NULL,
            unit_price DECIMAL(10,2) NOT NULL,
            supplier_id INT REFERENCES supplier(id),
            shelf_life_days INT DEFAULT 180,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # ---- 库存 (inventory) ----
    op.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id SERIAL PRIMARY KEY,
            product_id INT REFERENCES product(id) NOT NULL,
            store_id INT REFERENCES store(id) NOT NULL,
            quantity INT DEFAULT 0,
            safety_stock INT DEFAULT 10,
            last_restock_date TIMESTAMP,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # ---- 采购单 (purchase_order) ----
    op.execute("""
        CREATE TABLE IF NOT EXISTS purchase_order (
            id SERIAL PRIMARY KEY,
            supplier_id INT REFERENCES supplier(id) NOT NULL,
            product_id INT REFERENCES product(id) NOT NULL,
            quantity INT NOT NULL,
            unit_cost DECIMAL(10,2) NOT NULL,
            total_cost DECIMAL(12,2) NOT NULL,
            order_date TIMESTAMP DEFAULT NOW(),
            received_date TIMESTAMP,
            status VARCHAR(20) DEFAULT 'pending'
        )
    """)

    # =========================================================================
    # 种子数据
    # =========================================================================

    # ---- 供应商（8 家） ----
    op.execute("""
        INSERT INTO supplier (id, supplier_name, category, contact, phone, lead_time_days, on_time_rate, quality_score, status) VALUES
        (1,  '光明乳业',      '乳制品', '王经理', '13800001001', 3,  98.50, 4.8, 'active'),
        (2,  '中粮集团',      '粮油',   '李经理', '13800001002', 5,  95.00, 4.5, 'active'),
        (3,  '三只松鼠食品',  '零食',   '张经理', '13800001003', 4,  92.00, 4.3, 'active'),
        (4,  '康师傅饮品',    '饮料',   '刘经理', '13800001004', 3,  96.00, 4.6, 'active'),
        (5,  '寿光蔬菜基地',  '生鲜',   '赵经理', '13800001005', 1,  90.00, 4.2, 'active'),
        (6,  '恒安集团',      '日用品', '陈经理', '13800001006', 7,  94.00, 4.4, 'active'),
        (7,  '维达纸业',      '日用品', '周经理', '13800001007', 5,  97.00, 4.7, 'active'),
        (8,  '金龙鱼粮油',    '粮油',   '吴经理', '13800001008', 4,  93.00, 4.1, 'suspended')
        ON CONFLICT (id) DO NOTHING
    """)

    # ---- 商品（30 个，6 品类各 5 个） ----
    op.execute("""
        INSERT INTO product (id, product_name, category, unit_price, supplier_id, shelf_life_days) VALUES
        -- 生鲜
        (1,  '有机西红柿',   '生鲜',   8.80,  5, 7),
        (2,  '新鲜菠菜',     '生鲜',   5.50,  5, 5),
        (3,  '进口牛油果',   '生鲜',  15.00,  5, 10),
        (4,  '土鸡蛋（10枚）','生鲜',  22.00,  5, 30),
        (5,  '鲜猪肉（500g）','生鲜',  28.00,  5, 3),
        -- 乳制品
        (6,  '纯牛奶（1L）', '乳制品', 12.00,  1, 180),
        (7,  '原味酸奶（8杯）','乳制品',18.00,  1, 21),
        (8,  '儿童奶酪棒',   '乳制品', 25.00,  1, 90),
        (9,  '低脂酸奶',     '乳制品', 15.00,  1, 21),
        (10, '鲜奶油（200ml）','乳制品',22.00,  1, 14),
        -- 饮料
        (11, '冰红茶（500ml）','饮料',  3.50,  4, 365),
        (12, '矿泉水（550ml）','饮料',  2.00,  4, 730),
        (13, '橙汁（1L）',    '饮料',  9.90,  4, 180),
        (14, '功能性饮料',    '饮料',  6.00,  4, 365),
        (15, '无糖茶饮',      '饮料',  5.00,  4, 270),
        -- 零食
        (16, '每日坚果（25g）','零食', 12.00,  3, 180),
        (17, '薯片（大包）',  '零食',   8.50,  3, 270),
        (18, '夹心饼干',      '零食',  10.00,  3, 365),
        (19, '牛肉干（100g）','零食',  35.00,  3, 180),
        (20, '巧克力礼盒',    '零食',  68.00,  3, 365),
        -- 粮油
        (21, '大米（5kg）',    '粮油', 35.00,  2, 365),
        (22, '花生油（5L）',   '粮油', 89.00,  2, 540),
        (23, '面粉（2.5kg）',  '粮油', 15.00,  2, 365),
        (24, '橄榄油（500ml）','粮油', 55.00,  8, 540),
        (25, '杂粮礼盒',       '粮油', 78.00,  2, 365),
        -- 日用品
        (26, '抽纸（3包装）',  '日用品',15.00,  7, 1095),
        (27, '洗衣液（2kg）',  '日用品',35.00,  6, 730),
        (28, '洗洁精（1L）',   '日用品',12.00,  6, 730),
        (29, '厨房湿巾',       '日用品',18.00,  7, 730),
        (30, '垃圾袋（100只）','日用品',10.00,  6, 1095)
        ON CONFLICT (id) DO NOTHING
    """)

    # ---- 库存（90 条：30 商品 × 3 个活跃门店） ----
    op.execute("""
        INSERT INTO inventory (product_id, store_id, quantity, safety_stock, last_restock_date) VALUES
        -- 门店 1（华东旗舰店）
        (1,1,50,20,'2026-06-08'),(2,1,30,25,'2026-06-07'),(3,1,8,15,'2026-06-05'),
        (4,1,40,30,'2026-06-09'),(5,1,15,10,'2026-06-09'),(6,1,100,50,'2026-06-08'),
        (7,1,60,40,'2026-06-07'),(8,1,25,20,'2026-06-06'),(9,1,35,25,'2026-06-07'),
        (10,1,12,15,'2026-06-05'),(11,1,200,80,'2026-06-09'),(12,1,500,200,'2026-06-09'),
        (13,1,80,50,'2026-06-08'),(14,1,120,60,'2026-06-08'),(15,1,90,50,'2026-06-09'),
        (16,1,45,30,'2026-06-07'),(17,1,70,40,'2026-06-08'),(18,1,55,35,'2026-06-07'),
        (19,1,20,15,'2026-06-06'),(20,1,10,10,'2026-06-05'),(21,1,40,30,'2026-06-09'),
        (22,1,25,20,'2026-06-08'),(23,1,35,25,'2026-06-09'),(24,1,8,10,'2026-06-06'),
        (25,1,5,8,'2026-06-05'),(26,1,150,80,'2026-06-09'),(27,1,90,60,'2026-06-08'),
        (28,1,100,70,'2026-06-09'),(29,1,55,40,'2026-06-08'),(30,1,200,100,'2026-06-09'),
        -- 门店 2（华北中心店）
        (1,2,35,20,'2026-06-07'),(2,2,3,25,'2026-06-01'),(3,2,12,15,'2026-06-06'),
        (4,2,55,30,'2026-06-08'),(5,2,8,10,'2026-06-08'),(6,2,120,50,'2026-06-09'),
        (7,2,45,40,'2026-06-06'),(8,2,30,20,'2026-06-07'),(9,2,40,25,'2026-06-08'),
        (10,2,5,15,'2026-06-02'),(11,2,180,80,'2026-06-09'),(12,2,450,200,'2026-06-09'),
        (13,2,65,50,'2026-06-07'),(14,2,100,60,'2026-06-08'),(15,2,75,50,'2026-06-09'),
        (16,2,38,30,'2026-06-06'),(17,2,55,40,'2026-06-07'),(18,2,60,35,'2026-06-08'),
        (19,2,12,15,'2026-06-04'),(20,2,8,10,'2026-06-05'),(21,2,50,30,'2026-06-09'),
        (22,2,30,20,'2026-06-08'),(23,2,40,25,'2026-06-09'),(24,2,6,10,'2026-06-06'),
        (25,2,7,8,'2026-06-07'),(26,2,170,80,'2026-06-09'),(27,2,80,60,'2026-06-07'),
        (28,2,110,70,'2026-06-09'),(29,2,45,40,'2026-06-07'),(30,2,180,100,'2026-06-09'),
        -- 门店 3（华南旗舰店）
        (1,3,42,20,'2026-06-08'),(2,3,0,25,'2026-05-20'),(3,3,5,15,'2026-06-03'),
        (4,3,48,30,'2026-06-09'),(5,3,2,10,'2026-06-06'),(6,3,95,50,'2026-06-08'),
        (7,3,55,40,'2026-06-07'),(8,3,0,20,'2026-05-28'),(9,3,30,25,'2026-06-06'),
        (10,3,18,15,'2026-06-07'),(11,3,220,80,'2026-06-09'),(12,3,480,200,'2026-06-09'),
        (13,3,75,50,'2026-06-08'),(14,3,110,60,'2026-06-08'),(15,3,85,50,'2026-06-09'),
        (16,3,50,30,'2026-06-07'),(17,3,65,40,'2026-06-08'),(18,3,48,35,'2026-06-07'),
        (19,3,15,15,'2026-06-05'),(20,3,12,10,'2026-06-06'),(21,3,45,30,'2026-06-09'),
        (22,3,28,20,'2026-06-08'),(23,3,32,25,'2026-06-09'),(24,3,10,10,'2026-06-07'),
        (25,3,4,8,'2026-06-04'),(26,3,160,80,'2026-06-09'),(27,3,85,60,'2026-06-08'),
        (28,3,105,70,'2026-06-09'),(29,3,50,40,'2026-06-08'),(30,3,190,100,'2026-06-09')
        ON CONFLICT DO NOTHING
    """)

    # ---- 采购单（50 条，覆盖最近 3 个月） ----
    op.execute("""
        INSERT INTO purchase_order (id, supplier_id, product_id, quantity, unit_cost, total_cost, order_date, received_date, status) VALUES
        (1,5,1,100,6.50,650.00,'2026-05-20','2026-05-21','received'),
        (2,5,2,80,4.00,320.00,'2026-05-20','2026-05-21','received'),
        (3,1,6,200,9.00,1800.00,'2026-05-22','2026-05-25','received'),
        (4,1,7,150,14.00,2100.00,'2026-05-22','2026-05-25','received'),
        (5,4,11,500,2.50,1250.00,'2026-05-25','2026-05-28','received'),
        (6,4,12,1000,1.20,1200.00,'2026-05-25','2026-05-28','received'),
        (7,3,16,120,9.00,1080.00,'2026-05-28','2026-06-01','received'),
        (8,3,17,150,6.00,900.00,'2026-05-28','2026-06-01','received'),
        (9,2,21,80,28.00,2240.00,'2026-06-01','2026-06-06','received'),
        (10,2,22,60,72.00,4320.00,'2026-06-01','2026-06-06','received'),
        (11,7,26,300,10.00,3000.00,'2026-06-02','2026-06-09','received'),
        (12,6,27,200,25.00,5000.00,'2026-06-02','2026-06-09','received'),
        (13,5,3,50,12.00,600.00,'2026-06-05','2026-06-06','received'),
        (14,5,4,80,18.00,1440.00,'2026-06-05','2026-06-06','received'),
        (15,1,8,60,20.00,1200.00,'2026-06-05','2026-06-08','received'),
        (16,4,13,150,7.00,1050.00,'2026-06-06','2026-06-09','received'),
        (17,4,14,200,4.50,900.00,'2026-06-06','2026-06-09','received'),
        (18,3,18,130,7.50,975.00,'2026-06-08','2026-06-11','received'),
        (19,3,19,50,28.00,1400.00,'2026-06-08','2026-06-11','received'),
        (20,2,23,90,11.00,990.00,'2026-06-08','2026-06-13','received'),
        (21,2,25,30,60.00,1800.00,'2026-06-09','2026-06-14','received'),
        (22,6,28,180,8.50,1530.00,'2026-06-09','2026-06-16','received'),
        (23,7,29,120,13.00,1560.00,'2026-06-09','2026-06-16','received'),
        (24,8,24,25,45.00,1125.00,'2026-06-01','2026-06-05','received'),
        (25,1,9,80,11.00,880.00,'2026-06-10',NULL,'pending'),
        (26,1,10,30,17.00,510.00,'2026-06-10',NULL,'pending'),
        (27,4,15,160,3.50,560.00,'2026-06-10',NULL,'pending'),
        (28,3,20,20,52.00,1040.00,'2026-06-10',NULL,'pending'),
        (29,5,1,120,6.50,780.00,'2026-06-08','2026-06-09','received'),
        (30,5,5,40,22.00,880.00,'2026-06-08','2026-06-09','received'),
        (31,1,6,180,9.20,1656.00,'2026-06-08','2026-06-11','received'),
        (32,2,21,100,27.50,2750.00,'2026-06-05','2026-06-10','received'),
        (33,7,26,250,10.20,2550.00,'2026-06-05','2026-06-12','received'),
        (34,6,27,180,25.50,4590.00,'2026-06-07','2026-06-14','received'),
        (35,3,16,100,9.50,950.00,'2026-06-10',NULL,'pending'),
        (36,4,12,800,1.30,1040.00,'2026-06-10',NULL,'pending'),
        (37,5,2,90,4.20,378.00,'2026-06-07','2026-06-08','received'),
        (38,5,4,70,18.50,1295.00,'2026-06-07','2026-06-08','received'),
        (39,1,7,130,14.50,1885.00,'2026-06-06','2026-06-09','received'),
        (40,2,22,50,73.00,3650.00,'2026-06-03','2026-06-08','received'),
        (41,7,29,100,13.50,1350.00,'2026-06-03','2026-06-10','received'),
        (42,6,28,150,8.80,1320.00,'2026-06-04','2026-06-11','received'),
        (43,3,17,140,6.20,868.00,'2026-06-04','2026-06-08','received'),
        (44,4,13,130,7.20,936.00,'2026-06-02','2026-06-05','received'),
        (45,8,24,20,46.00,920.00,'2026-05-25','2026-05-29','received'),
        (46,2,23,80,11.50,920.00,'2026-05-25','2026-05-30','received'),
        (47,5,3,45,12.50,562.50,'2026-06-09','2026-06-10','received'),
        (48,1,8,55,20.50,1127.50,'2026-06-09',NULL,'pending'),
        (49,6,30,300,7.00,2100.00,'2026-06-10',NULL,'pending'),
        (50,3,18,120,7.80,936.00,'2026-06-09',NULL,'pending')
        ON CONFLICT (id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS purchase_order CASCADE")
    op.execute("DROP TABLE IF EXISTS inventory CASCADE")
    op.execute("DROP TABLE IF EXISTS product CASCADE")
    op.execute("DROP TABLE IF EXISTS supplier CASCADE")

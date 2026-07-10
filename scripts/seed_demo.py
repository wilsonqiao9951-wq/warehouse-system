from app.core.database import Base, SessionLocal, engine
from app.models import (
    InventoryTransaction,
    Part,
    TransactionType,
    User,
    UserRole,
    Warehouse,
    WorkOrder,
    WorkOrderPart,
)

Base.metadata.create_all(bind=engine)

db = SessionLocal()
try:
    if not db.query(User).first():
        wilson = User(name="Wilson", email="wilson@example.com", role=UserRole.ADMIN)
        manager = User(name="Mia", email="mia@example.com", role=UserRole.MANAGER)
        warehouse_user = User(name="Wade", email="wade@example.com", role=UserRole.WAREHOUSE)
        john = User(name="John", email="john@example.com", role=UserRole.ENGINEER)
        amy = User(name="Amy", email="amy@example.com", role=UserRole.ENGINEER)
        assistant = User(name="Alice", email="alice@example.com", role=UserRole.ASSISTANT)
        db.add_all([wilson, manager, warehouse_user, john, amy, assistant])
        db.flush()

        main_wh = Warehouse(name="Main Warehouse", location="Main storage")
        john_van = Warehouse(name="John Van", location="Field vehicle", assigned_user_id=john.id)
        amy_van = Warehouse(name="Amy Van", location="Field vehicle", assigned_user_id=amy.id)
        db.add_all([main_wh, john_van, amy_van])
        db.flush()

        valve = Part(
            part_number="FS-VALVE-001",
            name="Soda Solenoid Valve",
            english_name="Soda Solenoid Valve",
            machine_type="Freestyle",
            default_cost=45,
            safety_stock=2,
        )
        fan = Part(
            part_number="VP-FAN-001",
            name="Condenser Fan Motor",
            english_name="Condenser Fan Motor",
            machine_type="Viper",
            default_cost=85,
            safety_stock=1,
        )
        pump = Part(
            part_number="IC-PUMP-003",
            name="Carbonator Pump",
            english_name="Carbonator Pump",
            machine_type="Ice Combo",
            default_cost=120,
            safety_stock=1,
        )
        db.add_all([valve, fan, pump])
        db.flush()

        db.add_all(
            [
                InventoryTransaction(
                    part_id=valve.id,
                    transaction_type=TransactionType.INBOUND,
                    quantity=20,
                    to_warehouse_id=main_wh.id,
                    unit_cost=45,
                    notes="Initial inbound stock",
                ),
                InventoryTransaction(
                    part_id=fan.id,
                    transaction_type=TransactionType.INBOUND,
                    quantity=10,
                    to_warehouse_id=main_wh.id,
                    unit_cost=85,
                    notes="Initial inbound stock",
                ),
                InventoryTransaction(
                    part_id=pump.id,
                    transaction_type=TransactionType.INBOUND,
                    quantity=8,
                    to_warehouse_id=main_wh.id,
                    unit_cost=120,
                    notes="Initial inbound stock",
                ),
                InventoryTransaction(
                    part_id=valve.id,
                    transaction_type=TransactionType.TRANSFER,
                    quantity=4,
                    from_warehouse_id=main_wh.id,
                    to_warehouse_id=john_van.id,
                    user_id=john.id,
                    unit_cost=45,
                    notes="Stock assigned to John van",
                ),
                InventoryTransaction(
                    part_id=fan.id,
                    transaction_type=TransactionType.TRANSFER,
                    quantity=2,
                    from_warehouse_id=main_wh.id,
                    to_warehouse_id=john_van.id,
                    user_id=john.id,
                    unit_cost=85,
                    notes="Stock assigned to John van",
                ),
                InventoryTransaction(
                    part_id=valve.id,
                    transaction_type=TransactionType.TRANSFER,
                    quantity=2,
                    from_warehouse_id=main_wh.id,
                    to_warehouse_id=amy_van.id,
                    user_id=amy.id,
                    unit_cost=45,
                    notes="Stock assigned to Amy van",
                ),
            ]
        )
        db.flush()

        work_order = WorkOrder(
            ticket_number="WO-1001",
            store_name="Downtown Store",
            address="123 Main St",
            machine_type="Freestyle",
            assigned_user_id=john.id,
            engineer_id=john.id,
            assistant_id=assistant.id,
            revenue=420.0,
            labor_cost=90.0,
            status="completed",
        )
        db.add(work_order)
        db.flush()

        used_part = WorkOrderPart(
            work_order_id=work_order.id,
            part_id=valve.id,
            warehouse_id=john_van.id,
            user_id=john.id,
            quantity=1,
            unit_cost=45.0,
            installed="yes",
            old_part_returned="no",
            notes="Replaced leaking valve",
        )
        db.add(used_part)
        db.flush()

        db.add(
            InventoryTransaction(
                part_id=valve.id,
                    transaction_type=TransactionType.WORK_ORDER_USED,
                quantity=1,
                from_warehouse_id=john_van.id,
                work_order_id=work_order.id,
                user_id=john.id,
                unit_cost=45.0,
                notes="Seed work order usage",
            )
        )

        db.commit()
        print("Demo data created with inventory transactions and work order usage")
    else:
        print("Demo data already exists")
finally:
    db.close()

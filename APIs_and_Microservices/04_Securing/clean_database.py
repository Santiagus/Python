from orders.repository.orders_repository import OrdersRepository
from orders.repository.unit_of_work import UnitOfWork

with UnitOfWork() as unit_of_work:
    orders_repository = OrdersRepository(unit_of_work.session)
    orders = orders_repository.list()
    for order in orders:
        orders_repository.delete(order.id)
    unit_of_work.commit()

<?php

use App\Models\Order;
use Illuminate\Database\Migrations\Migration;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        DB::table('orders')->where('status', 'new')->update(['status' => 'pending']);
        Order::all()->each(fn ($o) => $o->touch());
        DB::statement('ALTER TABLE orders ENGINE=InnoDB');
        Schema::dropIfExists('order_archive');
        Schema::rename('carts', 'baskets');
    }

    public function down(): void
    {
    }
};

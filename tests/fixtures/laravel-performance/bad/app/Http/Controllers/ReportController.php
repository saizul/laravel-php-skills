<?php

namespace App\Http\Controllers;

use App\Models\Order;

class ReportController extends Controller
{
    public function index()
    {
        $orders = Order::all();
        $count = Order::where('paid', true)->get()->count();
        $any = Order::where('refunded', true)->get()->isEmpty();
        // env('IN_A_COMMENT') is ignored
        $key = env('STRIPE_KEY');

        return view('reports', compact('orders', 'count', 'any', 'key'));
    }
}

<?php

namespace App\Http\Controllers;

use App\Models\Order;

class ReportController extends Controller
{
    public function index()
    {
        return view('reports', [
            'orders' => Order::latest()->paginate(50),
            'count' => Order::where('paid', true)->count(),
            'key' => config('services.stripe.key'),
        ]);
    }
}
